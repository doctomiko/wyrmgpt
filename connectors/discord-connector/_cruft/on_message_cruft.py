        # Detailed ambient reply suppression logic - legacy commented code
        #suppress = False
        #bot_mentioned = False
        #try:
        #    bot_mentioned = (self.user is not None) and (
        #        (f"<@{self.user.id}>" in (message.content or "")) or (f"<@!{self.user.id}>" in (message.content or ""))
        #    )
        #except Exception:
        #    bot_mentioned = False

        #ref_msg_id = None
        #try:
        #    ref_msg_id = getattr(getattr(message, "reference", None), "message_id", None)
        #except Exception:
        #    ref_msg_id = None

        #pseudo_reply = False
        #first_token = ""
        #try:
        #    first_token = (message.content or "").strip().split(maxsplit=1)[0] if (message.content or "").strip() else ""
        #    # If the message *starts* with another user's mention, treat it like a reply (unless Callie is mentioned later).
        #    pseudo_reply = first_token.startswith("<@") and (not bot_mentioned)
        #except Exception:
        #    pseudo_reply = False
        #
        #suppress_ambient_replies = await cfg.suppress_ambient_replies()
        #if ambient_mode and (not invoked) and suppress_ambient_replies:
        #    if (ref_msg_id is not None) or pseudo_reply:
        #        # If it's a reply, fetch the referenced message; suppress unless it's a reply to Callie, or bot is mentioned.
        #        if bot_mentioned:
        #            suppress = False
        #        else:
        #            is_reply_to_callie = False
        #            try:
        #                if ref_msg_id is not None:
        #                    ref = await message.channel.fetch_message(ref_msg_id)
        #                    is_reply_to_callie = (ref is not None) and (ref.author is not None) and (self.user is not None) and (ref.author.id == self.user.id)
        #            except Exception:
        #                # If we can't resolve the reference, assume it's not Callie.
        #                is_reply_to_callie = False
        #
        #            suppress = (not is_reply_to_callie)
        #
        # Apply suppression to should_respond (ambient only).
        #if suppress:
        #    should_respond = False
        #
        #log.info(
        #    f"Gate: ambient reply-check disable={suppress_ambient_replies} bot_mentioned={bot_mentioned} "
        #    f"ref={'yes' if ref_msg_id else 'no'} ref_msg_id={ref_msg_id} pseudo={pseudo_reply} "
        #    f"first_token={first_token!r} suppress={suppress}"
        #)


        # Legacy PK code
        #try:
        #    if getattr(message, "webhook_id", None) and member is not None and isinstance(member_res_meta, str) and member_res_meta.startswith("proxied"):
        #        proxy_name = getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Unknown"
        #        server_ctx += (
        #            "\n\n[Proxy note]\n"
        #            "This message was posted via a webhook/proxy (likely PluralKit).\n"
        #            f"Visible proxy name: {proxy_name}\n"
        #            f"Resolved system account for permissions: {getattr(member, 'display_name', getattr(member, 'name', 'Unknown'))} (id={getattr(member, 'id', 'Unknown')})\n"
        #            "Use the resolved system account for role/permission assumptions, but address the user conversationally by the visible proxy name when appropriate."
        #        )
        #except Exception:
        #    pass



            # if cfg.require_guild_context() and not server_ctx.strip():
            #    log.error(f"Hard-stop: missing server_ctx for msg_id={message.id} author_id={message.author.id}")
            #    await message.reply("(connector error: missing server context; refusing to call model)", mention_author=False)
            #    return        



        #extra_parts: List[Dict] = []
        #attachment_notes: List[str] = []
        #shielded_notes_user: List[str] = []
        #if invoked and message.attachments:
        #    blocked: List[str] = []
        #    shielded: List[str] = []
        #
        ## Important: we DO NOT process attachments in ambient-only mode.
        ## We process what we can and "shield" the rest, but we do NOT abort the message.
        #for att in message.attachments:
        #    fname = att.filename or "(unnamed)"
        #    ext = os.path.splitext(fname)[1].lower()
        #
        #    # Hard block executables/binaries.
        #    if ext in await cfg.blocked_attachment_exts():
        #        blocked.append(fname)
        #        continue
        #
        #    # Unknown type: shield it (but keep going).
        #    allowed_exts = await cfg.allowed_attachment_exts()
        #    if ext and ext not in (allowed_exts or []):
        #        shielded.append(f"{fname} (unsupported type: {ext})")
        #        continue
        #
        #    # If it is extremely large, shield it (Files API still has limits; we don't want surprises).
        #    max_api_bytes = await cfg.max_files_api_bytes()
        #    if att.size is not None and att.size > max_api_bytes:
        #        shielded.append(f"{fname} (too large: {att.size} bytes; Files API cap {max_api_bytes} bytes)")
        #        continue
        #
        #    # Download bytes from Discord.
        #    try:
        #        async with httpx.AsyncClient(timeout=90.0) as dl:
        #            r = await dl.get(att.url)
        #            r.raise_for_status()
        #            data = r.content
        #    except Exception as e:
        #        shielded.append(f"{fname} (download failed: {type(e).__name__})")
        #        continue
        #
        #    # Determine file kind
        #    mime = (att.content_type or "").lower()
        #    is_pdf = ext == ".pdf" or mime == "application/pdf"
        #    is_image = mime.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
        #
        #    max_attachment_mb = await cfg.max_attachment_mb()
        #    max_attachment_bytes = max_attachment_mb * 1024 * 1024
        #    # Inline images + PDFs under the inline cap; otherwise upload to Files API.
        #    if is_image and len(data) <= max_attachment_bytes:
        #        if not mime.startswith("image/"):
        #            # Best-effort mime for common images
        #            mime = "image/png" if ext == ".png" else "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/gif" if ext == ".gif" else "image/webp" if ext == ".webp" else "image/*"
        #        b64 = base64.b64encode(data).decode("utf-8")
        #        extra_parts.append({
        #            "type": "input_image",
        #            "image_url": f"data:{mime};base64,{b64}",
        #        })
        #        attachment_notes.append(f"image attached inline: {fname} ({len(data)} bytes)")
        #        continue
        #
        #    if is_pdf and len(data) <= max_attachment_bytes:
        #        b64 = base64.b64encode(data).decode("utf-8")
        #        extra_parts.append({
        #            "type": "input_file",
        #            "filename": fname,
        #            "file_data": f"data:application/pdf;base64,{b64}",
        #        })
        #        attachment_notes.append(f"PDF attached inline: {fname} ({len(data)} bytes)")
        #        continue
        #
        #    # Everything else (including large PDFs/images): upload to Files API, and include a note with the file id.
        #    try:
        #        api_key = await cfg.openai_api_key()
        #        file_id = await openai_upload_file(data=data, filename=fname, purpose="user_data", api_key=api_key)
        #        attachment_notes.append(f"file uploaded: {fname} (file_id={file_id})")
        #    except Exception as e:
        #        shielded.append(f"{fname} (upload failed: {type(e).__name__})")
        #
        #    if blocked:
        #        shielded_notes_user.append(
        #            "Shielded executable/binary attachments (Callie does not process these): " + ", ".join(blocked)
        #        )
        #    if shielded:
        #        shielded_notes_user.append(
        #            "Shielded some attachments: " + "; ".join(shielded)
        #        )
        #
        #    if attachment_notes:
        #            # Short note for the model, regardless of inline vs file upload.
        #            extra_parts.append({
        #                "type": "input_text",
        #                "text": "Connector note: " + " | ".join(attachment_notes),
        #            })
        #    if shielded_notes_user:
        #        # Also tell the model what was shielded so it doesn't assume it can access it.
        #        extra_parts.append({
        #            "type": "input_text",
        #            "text": "Connector note (shielded attachments not provided to model): " + " | ".join(shielded_notes_user),
        #        })




            # A previous version 
            # sent_messages: List[discord.Message] = []
            # for idx, chunk in enumerate(chunks):
            #     part = idx + 1
            #     total = len(chunks)
            #     if idx == 0:
            #         factory = lambda ch=chunk: message.reply(ch, mention_author=False)
            #     else:
            #         factory = lambda ch=chunk: message.channel.send(ch, reference=message, silent=True)
            #     sent = await send_with_retry(factory, part_idx=part, total_parts=total)
            #     if not sent:
            #         break
            #     sent_messages.append(sent)
            #     log.info(f"TX ok part={part}/{total} sent_msg_id={sent.id} chars={len(chunk)}")
                
            # We improved the throttling and error handling for this...
            # So it would work in a loop
            # try:
            #   sent_messages.append(sent)
            #   log.info(f"TX ok part={idx+1}/{len(chunks)} sent_msg_id={sent.id} chars={len(chunk)}")
            # except discord.HTTPException as e:
            #   log.error(
            #       f"TX failed part={idx+1}/{len(chunks)} HTTPException "
            #       f"status={getattr(e, 'status', None)} code={getattr(e, 'code', None)} err={e}"
            #   )
            #   break
            # except Exception as e:
            #   log.error(f"TX failed part={idx+1}/{len(chunks)} err={type(e).__name__}: {e}")
            #   log.debug(traceback.format_exc())
            #   break




