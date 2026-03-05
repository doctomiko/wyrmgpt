if (False): # Articles - Legacy versions of older code
    def get_artifact_text(conn, artifact_id: str, *, data_dir: str = "data") -> str:
        row = conn.execute(
            "SELECT content_text, sidecar_path FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            return ""
        content_text, sidecar_path = row
        if content_text is not None:
            return content_text
        if sidecar_path:
            p = Path(data_dir) / sidecar_path
            try:
                return p.read_text(encoding="utf-8")
            except FileNotFoundError:
                return ""
        return ""

    def list_artifacts_for_conversation(
        conversation_id: str,
        include_deleted: bool = False,
    ) -> list[dict]:
        """
        Return all artifacts linked to a conversation, optionally excluding soft-deleted.
        """
        conversation_id = (conversation_id or "").strip()
        if not conversation_id:
            raise ValueError("conversation_id is required.")

        with db_session() as conn:
            _ensure_conversation_exists(conn, conversation_id)
            sql = """
                SELECT a.*
                FROM conversation_artifacts ca
                JOIN artifacts a ON a.id = ca.artifact_id
                WHERE ca.conversation_id = ?
            """
            params: list[object] = [conversation_id]
            if not include_deleted:
                sql += " AND (a.is_deleted IS NULL OR a.is_deleted = 0)"
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_artifacts_for_project(
        project_id: int,
        include_deleted: bool = False,
    ) -> list[dict]:
        """
        Convenience to fetch all artifacts under a project.
        Right now it's just a straight select on artifacts.project_id.
        """
        if project_id is None:
            raise ValueError("project_id is required.")

        with db_session() as conn:
            _ensure_project_exists(conn, int(project_id))
            sql = """
                SELECT *
                FROM artifacts
                WHERE project_id = ?
            """
            params: list[object] = [int(project_id)]
            if not include_deleted:
                sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
            rows = conn.execute(sql, params).fetchall()

        return [dict(r) for r in rows]

    def list_artifacts_for_file(
        file_id: int | str,
        include_deleted: bool = False,
    ) -> list[dict]:
        """
        Return all artifacts associated with a given file_id (sent to db as source_id),
        ordered by chunk_index (if present) and updated_at.

        v8+: If an artifact has sidecar_path, hydrate sidecar content into:
        - content_text (preferred)
        - content (legacy fallback) if content is empty
        """
        file_id_str = str(file_id).strip()
        if not file_id_str:
            raise ValueError("file_id is required.")

        with db_session() as conn:
            _ensure_file_exists(conn, file_id_str)
            sql = """
                SELECT *
                FROM artifacts
                WHERE source_id = ?
            """
            params: list[object] = [file_id_str]
            if not include_deleted:
                sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
            sql += " ORDER BY updated_at ASC" # chunk_index ASC, 
            rows = conn.execute(sql, params).fetchall()

        out = [dict(r) for r in rows]

        # Hydrate sidecar content into the row dicts.
        for art in out:
            sidecar_path = (art.get("sidecar_path") or "").strip() or None
            if not sidecar_path:
                # If content_text is missing but legacy content exists, backfill content_text.
                if (art.get("content_text") is None or str(art.get("content_text") or "").strip() == "") and art.get("content"):
                    art["content_text"] = art.get("content")
                continue

            # If content_text already present, prefer it and don't re-read.
            existing_ct = art.get("content_text")
            if existing_ct is not None and str(existing_ct).strip() != "":
                # Keep legacy compatibility too if content is empty.
                if not (art.get("content") or "").strip():
                    art["content"] = str(existing_ct)
                continue

            # Read sidecar
            p = Path(DATA_DIR) / sidecar_path
            try:
                text = p.read_text(encoding="utf-8")
            except FileNotFoundError:
                text = ""
            except Exception as exc:
                print(f"[db] sidecar read failed for artifact {art.get('id')}: {sidecar_path} ({exc})")
                text = ""

            art["content_text"] = text

            # Legacy fallback: if content is empty, mirror hydrated text into content
            #if not (art.get("content") or "").strip():
            #    art["content"] = text

        print(f"[db] list_artifacts_for_file({file_id_str!r}, include_deleted={include_deleted}) -> {len(out)} rows")
        return out

    def list_artifacts_for_file(
        file_id: int | str,
        include_deleted: bool = False,
    ) -> list[dict]:
        """
        Return all artifacts associated with a given file_id,
        ordered by chunk_index (if present) and updated_at.
        """
        file_id_str = str(file_id).strip()
        if not file_id_str:
            raise ValueError("file_id is required.")

        with db_session() as conn:
            _ensure_file_exists(conn, file_id_str)
            sql = """
                SELECT *
                FROM artifacts
                WHERE file_id = ?
            """
            params: list[object] = [file_id_str]
            if not include_deleted:
                sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
            sql += " ORDER BY updated_at ASC" # chunk_index ASC, 
            rows = conn.execute(sql, params).fetchall()

        print(f"[db] list_artifacts_for_file({file_id_str!r}, include_deleted={include_deleted}) -> {len(rows)} rows")
        return [dict(r) for r in rows]

    def _artifact_id_for_file(file_id: str) -> str:
        return f"file:{file_id}"

    def create_scoped_artifact(
        project_id: int,
        name: str,
        content: str,
        tags: Any = None,
        *,
        scope_type: str | None = None,
        scope_id: int | None = None,
        scope_uuid: str | None = None,
        file_id: str | None = None,
        source_kind: str | None = None,
        provenance: str | None = None,
        chunk_index: int | None = None,
    ) -> dict:
        """
        Extended artifact-creation helper that fills the additional schema columns.

        This is the variant you should use for file-/scope-aware artifacts
        and for multi-chunk file artifacts (via chunk_index).
        """
        if project_id is None:
            raise ValueError("project_id is required.")
        name = (name or "").strip()
        content = (content or "").strip()
        if not name:
            raise ValueError("Artifact name cannot be empty.")
        if not content:
            raise ValueError("Artifact content cannot be empty.")

        tags_text = _normalize_tags(tags)
        scope_type = (scope_type or "").strip() or None
        scope_uuid = (scope_uuid or "").strip() or None
        file_id = (file_id or "").strip() or None
        source_kind = (source_kind or "").strip() or None
        provenance = (provenance or "").strip() or None

        if chunk_index is None:
            chunk_index_int: int | None = None
        else:
            try:
                chunk_index_int = int(chunk_index)
            except (TypeError, ValueError):
                raise ValueError("chunk_index must be an integer or None.")
            if chunk_index_int < 0:
                raise ValueError("chunk_index cannot be negative.")

        aid = str(uuid.uuid4())
        now = _utc_now_iso()

        with db_session() as conn:
            _ensure_project_exists(conn, int(project_id))
            conn.execute(
                """
                INSERT INTO artifacts (
                    id,
                    project_id,
                    name,
                    content,
                    tags,
                    scope_type,
                    scope_id,
                    scope_uuid,
                    file_id,
                    source_kind,
                    provenance,
                    chunk_index,
                    is_deleted,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    aid,
                    int(project_id),
                    name,
                    content,
                    tags_text,
                    scope_type,
                    scope_id,
                    scope_uuid,
                    file_id,
                    source_kind,
                    provenance,
                    chunk_index_int,
                    now,
                ),
            )

        return {"id": aid}

    def create_artifact(project_id: int, name: str, content: str, tags: Any = None) -> dict:
        if project_id is None:
            raise ValueError("project_id is required.")
        name = (name or "").strip()
        content = (content or "").strip()
        tags_text = _normalize_tags(tags)  # from earlier memory helper; ok if tags is str/None/list
        if not name:
            raise ValueError("Artifact name cannot be empty.")
        if not content:
            raise ValueError("Artifact content cannot be empty.")

        aid = deterministic_artifact_id()
        # new_uuid()
        with db_session() as conn:
            _ensure_project_exists(conn, int(project_id))
            conn.execute(
                """
                INSERT INTO artifacts (id, project_id, name, content, tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (aid, int(project_id), name, content, tags_text, _utc_now_iso()),
            )
        return {"id": aid}

    def create_file_artifacts(
        *,
        file_row: dict,
        project_id: int,
        scope_type: str | None,
        scope_id: int | None,
        scope_uuid: str | None,
        chunks: list[str],
        source_kind: str | None,
        provenance: str | None,
    ) -> list[str]:
        """
        Insert one artifact row per chunk for a given file.

        Handles soft-deleting the previous artifact set for that file_id.

        Returns the list of artifact IDs.
        """
        from .db import soft_delete_artifacts_for_file  # safe self-import once module is loaded

        file_id = file_row.get("id")
        if not file_id:
            raise ValueError("file_row missing 'id'")

        file_id_str = str(file_id)

        # Soft delete old artifacts for this file.
        try:
            soft_delete_artifacts_for_file(file_id_str)
        except Exception as e:
            # Fallback if helper is missing or fails (during odd migration states).
            now = _utc_now_iso()
            with db_session() as conn:
                conn.execute(
                    """
                    UPDATE artifacts
                    SET is_deleted = 1, deleted_at = ?
                    WHERE file_id = ?
                    AND (is_deleted IS NULL OR is_deleted = 0)
                    """,
                    (now, file_id_str),
                )

        artifact_ids: list[str] = []
        name = file_row.get("name") or Path(str(file_row.get("path", "file"))).name
        tags: Any = None

        for idx, chunk in enumerate(chunks):
            if not chunk:
                continue

            # Create the artifact row itself.
            try:
                art = create_scoped_artifact(
                    project_id=project_id,
                    name=name,
                    content=chunk,
                    tags=tags,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    scope_uuid=scope_uuid,
                    file_id=file_id_str,
                    source_kind=source_kind,
                    provenance=provenance,
                    chunk_index=idx,
                )
            except TypeError:
                # Fallback for older signature without chunk_index.
                art = create_scoped_artifact(
                    project_id=project_id,
                    name=name,
                    content=chunk,
                    tags=tags,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    scope_uuid=scope_uuid,
                    file_id=file_id_str,
                    source_kind=source_kind,
                    provenance=provenance,
                )

            art_id = art.get("id")
            if not art_id:
                continue

            artifact_ids.append(str(art_id))

            # If this file is conversation-scoped, link the artifact to that conversation.
            if scope_type == "conversation" and scope_uuid:
                try:
                    conversation_link_artifact(scope_uuid, str(art_id))
                except Exception:
                    # Don’t explode artifact creation just because linking failed.
                    pass

        return artifact_ids

    def rebuild_artifacts_from_files(conn, *, data_dir="data", sidecar_threshold_bytes=200_000) -> dict:
        files = conn.execute("SELECT id, path, mime_type, title FROM files").fetchall()

        created = 0
        for file_id, path, mime_type, title in files:
            # 1) Extract text from file on disk (YOU plug this in)
            # TODO this doesn't exist yet, what is the correct call here?
            text = extract_text_from_file(path, mime_type)  # <- your function

            artifact_id = new_uuid()
            conn.execute(
                """
                INSERT INTO artifacts (id, source_kind, scope_type, scope_id, source_id, title, updated_at)
                VALUES (?, 'file', 'global', NULL, ?, ?, ?)
                """,
                (artifact_id, file_id, title, _utc_now_iso()),
            )
            update_artifact_text(
                conn,
                artifact_id,
                text,
                source_kind="file",
                data_dir=data_dir,
                sidecar_threshold_bytes=sidecar_threshold_bytes,
            )
            created += 1

        return {"created": created}

    def get_artifact_text(conn, artifact_id: str, *, data_dir: str = "data") -> str:
        row = conn.execute(
            "SELECT content_text, sidecar_path FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            return ""

        content_text, sidecar_path = row
        if content_text is not None:
            return content_text

        if sidecar_path:
            p = Path(data_dir) / sidecar_path
            try:
                return p.read_text(encoding="utf-8")
            except FileNotFoundError:
                return ""

        return ""

    def get_artifact_text(conn, *, artifact_id=None, artifact_uuid=None, data_dir: str = "data") -> str:
        assert artifact_id is not None or artifact_uuid is not None

        cur = conn.cursor()
        if artifact_id is not None:
            cur.execute("""
                SELECT content_text, sidecar_path
                FROM artifacts
                WHERE num_id = ?
            """, (artifact_id,))
        else:
            cur.execute("""
                SELECT content_text, sidecar_path
                FROM artifacts
                WHERE id = ?
            """, (artifact_uuid,))

        row = cur.fetchone()
        if not row:
            return ""

        content_text, sidecar_path = row
        if content_text is not None:
            return content_text

        if sidecar_path:
            p = Path(data_dir) / sidecar_path
            try:
                return p.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Sidecar missing; treat as empty but you may want to log this.
                return ""
        return ""

    def update_artifact_text(
        conn,
        artifact_id: str,
        text: str,
        *,
        source_kind: str,
        data_dir: str = "data",
        sidecar_threshold_bytes: int = 200_000,
    ) -> None:
        if text is None:
            text = ""

        norm = text.replace("\r\n", "\n").replace("\r", "\n")
        content_bytes = len(norm.encode("utf-8"))
        content_hash = _sha256_hex(norm)

        row = conn.execute(
            "SELECT sidecar_path FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"artifact not found: {artifact_id}")
        old_sidecar_path = row[0]

        use_sidecar = content_bytes > sidecar_threshold_bytes

        if use_sidecar:
            # write file first
            new_sidecar_path = _write_artifact_sidecar(
                source_kind=source_kind, artifact_id=artifact_id, text=norm
            )

            conn.execute(
                """
                UPDATE artifacts
                SET content_text = NULL,
                    sidecar_path = ?,
                    content_hash = ?,
                    content_bytes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_sidecar_path, content_hash, content_bytes, _utc_now_iso(), artifact_id),
            )

            if old_sidecar_path and old_sidecar_path != new_sidecar_path:
                _delete_sidecar_if_exists(sidecar_path=old_sidecar_path)

        else:
            conn.execute(
                """
                UPDATE artifacts
                SET content_text = ?,
                    sidecar_path = NULL,
                    content_hash = ?,
                    content_bytes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (norm, content_hash, content_bytes, _utc_now_iso(), artifact_id),
            )

            if old_sidecar_path:
                _delete_sidecar_if_exists(sidecar_path=old_sidecar_path)
    
        def update_artifact_text(
            conn,
            *,
            artifact_id: int | None = None,
            artifact_uuid: str | None = None,
            text: str,
            source_kind: str = "misc",         # e.g. "files", "web", "memories", "messages"
            data_dir: str = "data",
            sidecar_threshold_bytes: int = 200_000,  # configurable
        ) -> None:
            """
            Update the text content of an artifact, deciding whether to store inline or in a sidecar file based on size.
            - If the text is small (<= sidecar_threshold_bytes), store it directly in the
                content_text column and clear sidecar_path.
            - If the text is large (> sidecar_threshold_bytes), write it to a sidecar file and store the path in sidecar_path, clearing content_text.
            """
            # TODO how is this considered an upsert if it only updates? Should we insert if not exists? For now we require the artifact to exist and just update it, since that's the main use case (managing content for an existing artifact), but we could extend this to also support inserting a new artifact if neither ID nor UUID is found.
            
            assert artifact_id is not None or artifact_uuid is not None
            if text is None:
                text = ""

            # Normalize line endings to keep hashing stable-ish across platforms
            norm = text.replace("\r\n", "\n").replace("\r", "\n")
            h = _sha256_hex(norm)
            b = len(norm.encode("utf-8"))

            cur = conn.cursor()
            if artifact_id is not None:
                cur.execute("SELECT id, sidecar_path, content_text FROM artifacts WHERE num_id = ?", (artifact_id,))
            else:
                cur.execute("SELECT id, sidecar_path, content_text FROM artifacts WHERE id = ?", (artifact_uuid,))

            row = cur.fetchone()
            if not row:
                raise ValueError("Artifact not found")

            db_uuid, old_sidecar_path, old_inline = row
            auuid = artifact_uuid or db_uuid

            # Decide storage mode
            use_sidecar = (b > sidecar_threshold_bytes)

            if use_sidecar:
                # Write file first, then update DB (so DB never points to missing content on success path)
                new_sidecar_path = write_artifact_sidecar(
                    data_dir=data_dir,
                    source_kind=source_kind,
                    artifact_uuid=auuid,
                    text=norm,
                )

                # Update DB: clear inline, set sidecar, hash/bytes/timestamp
                if artifact_id is not None:
                    cur.execute("""
                        UPDATE artifacts
                        SET content_text = NULL,
                            sidecar_path = ?,
                            content_hash = ?,
                            content_bytes = ?,
                            updated_at = ?
                        WHERE num_id = ?
                    """, (new_sidecar_path, h, b, _utc_now_iso(), artifact_id))
                else:
                    cur.execute("""
                        UPDATE artifacts
                        SET content_text = NULL,
                            sidecar_path = ?,
                            content_hash = ?,
                            content_bytes = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (new_sidecar_path, h, b, _utc_now_iso(), auuid))

                # If we switched from an old sidecar path that differs, delete the old one
                if old_sidecar_path and old_sidecar_path != new_sidecar_path:
                    delete_sidecar_if_exists(data_dir=data_dir, sidecar_path=old_sidecar_path)

            else:
                # Inline storage
                if artifact_id is not None:
                    cur.execute("""
                        UPDATE artifacts
                        SET content_text = ?,
                            sidecar_path = NULL,
                            content_hash = ?,
                            content_bytes = ?,
                            updated_at = ?
                        WHERE num_id = ?
                    """, (norm, h, b, _utc_now_iso(), artifact_id))
                else:
                    cur.execute("""
                        UPDATE artifacts
                        SET content_text = ?,
                            sidecar_path = NULL,
                            content_hash = ?,
                            content_bytes = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (norm, h, b, _utc_now_iso(), auuid))

                # If we used to have a sidecar, remove it (since inline is now canonical)
                if old_sidecar_path:
                    delete_sidecar_if_exists(data_dir=data_dir, sidecar_path=old_sidecar_path)

    def merge_legacy_article_chunks_to_single_pass(
        conn,
        *,
        data_dir: str = "data",
        sidecar_threshold_bytes: int = 200_000,
        chunk_index_col: str = "chunk_index", # confirmed schema v8
        uuid_col: str = "id",
        numid_col: str = "num_id",
        source_kind_col: str = "scope_type", # confirmed schema v8
    ) -> dict:
        """
        Merges chunked legacy articles where multiple rows share the same uuid.
        Keeps the lowest-id row as the canonical article row, deletes the rest.
        Writes merged content via upsert_article_text (so inline/sidecar is decided consistently).
        """
        cur = conn.cursor()

        # Find uuids with more than one row (legacy chunking)
        cur.execute(f"""
            SELECT {uuid_col}, COUNT(*) AS n
            FROM artifacts
            GROUP BY {uuid_col}
            HAVING n > 1
        """)
        groups = [r[0] for r in cur.fetchall()]

        merged_count = 0
        deleted_rows = 0

        for auuid in groups:
            # Fetch all rows for this uuid ordered by chunk index, then id for stability
            cur.execute(f"""
                SELECT {uuid_col} AS id, COALESCE({chunk_index_col}, 0) AS ck, {source_kind_col} AS sk, content_text AS ctext, sidecar_path AS spath
                FROM artifacts
                WHERE {uuid_col} = ?
                ORDER BY ck ASC, {numid_col} ASC
            """, (auuid,))
            rows = cur.fetchall()
            if not rows:
                continue

            canonical_id = rows[0][0] # Determine canonical row = first by ordering
            uuid_id = rows[0][uuid_col]
            num_id = rows[0][numid_col]
            source_kind = rows[0][source_kind_col] or "unknown"

            parts = []
            for (id, ck, sk, ctext, spath) in rows:
                if ctext is not None:
                    parts.append(ctext)
                elif spath:
                    parts.append((Path(data_dir) / spath).read_text(encoding="utf-8"))
                else:
                    parts.append("")

            merged_text = "\n".join(parts).strip()

            update_artifact_text(
                conn,
                artifact_uuid=auuid, #uuid_id, #id,
                artifact_id=num_id,
                text=merged_text,
                source_kind=source_kind,
                data_dir=data_dir,
                sidecar_threshold_bytes=sidecar_threshold_bytes,
            )

            # Delete other rows (and their sidecars) now that canonical holds merged content
            for (id, ck, sk, ctext, spath) in rows[1:]:
                if spath:
                    delete_sidecar_if_exists(data_dir=data_dir, sidecar_path=spath)
                cur.execute(f"DELETE FROM artifacts WHERE {uuid_col} = ?", (id,))
                deleted_rows += 1

            merged_count += 1

        return {"merged_articles": merged_count, "deleted_rows": deleted_rows}
