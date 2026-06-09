




# By default the Store will connect to the DB when __init__ is called
#store: "Store" = Store(global_config)
#config_mgr = ConfigManager(store, global_config)


            # Vivian - commented out because Callie said to do it
            # IMPORTANT: when recording, use decision.effective_author.author_id and .author_name,
            # not message.author, so PK messages are attributed to the owning user.
            #raw_author_name = decision.effective_author.author_name
            #author_name: str = ""
            #if inspect.isawaitable(raw_author_name):
            #    author_name = str(await raw_author_name)
            #else:
            #    author_name = str(raw_author_name)
            #if not author_name or author_name.strip() == "":
            #    author_name = pk_aware_author_name
            #author_id = int(decision.effective_author.author_id) or pk_aware_author_id



        #created_ts = int(sent.created_at.timestamp()) if getattr(sent, "created_at", None) else now_epoch()
        #await self.store.log_message(
        #    channel_id=sent.channel.id,
        #    discord_guild_id=sent.guild.id if sent.guild else 0,
        #    discord_message_id=sent.id,
        #    author_id=getattr(self.user, "id", 0),
        #    author_name="Callie",
        #    content=sanitize_content(sent.content),
        #    created_at=created_ts,
        #    is_callie=True
        #)



        #Ending to check_message_guild
        # Vivian this is no longer needed because of the check_message_guild above
        # Ensure `member` is defined: prefer message.author when it's a Member, else try guild lookups.
        #if member is None and message.guild is not None:
        #    member = message.author if isinstance(message.author, discord.Member) else None
        #    try:
        #        member = message.guild.get_member(message.author.id)
        #    except Exception:
        #        member = None
        #    member = message.guild.get_member(message.author.id)
        #    if member is None:
        #        try:
        #            member = await message.guild.fetch_member(message.author.id)
        #        except Exception:
        #            member = None



        # Vivian - commented out because Callie said to do it    
        # Ignore bots, but allow webhook-proxied messages (PluralKit-style)
        #if message.author.bot and not getattr(message, 'webhook_id', None):
        #    log.info("Ignore: message from bot author without a webhook_id (not PK)")
        #    return


        # BEGIN - Vivian wonders if we need this anymore or is it part of compute_access_decision now?

        # gate the message by whether it's in an allowed channel
        #is_allowed, cfg = await self.is_allowed_channel(message)
        #if not is_allowed:
        #    log.info("Gate: channel not allowed -> ignore")
        #    return

        #if (not cfg):
        #    cfg = self.config_mgr.check_guild(message)
        #assert cfg

        # END - Vivian wonders...



        # BEGIN Vivian - let's see what happens if we comment this out

        # Access gate check (per-guild)
        # TODO appears to be a bit redundant with is_allowed_channel above; refactor later
        # Might be totally redundant depending on how passes_access_gate_gc is implemented. 
        # This sets the channel for threads in channel
        #parent_channel_id = get_effective_channel_id(message, parent=True)
        #if not (await passes_access_gate_gc(cfg, parent_channel_id, member)):
        #    log.info("Gate: access denied")
        #    return
        #log.info("Gate: access granted")

        # BEGIN Vivian - let's see...



        ## TODO do we want the parent channel ID here instead for threads?
        #log.debug(f"Session state active={st.is_active} ambient={st.ambient} verbose={st.verbose} last_activity={st.last_activity}")
        #if (not st.is_active) and (parent_channel_id != session_channel_id):
        #    parent_st = await self.store.get_session(parent_channel_id)
        #    if parent_st.is_active:
        #        st = parent_st
        #        log.info("Gate: inheriting active session from parent channel (thread=%s parent=%s)", session_channel_id, parent_channel_id)
        #if st is not None and not st.is_active:
        #    log.info("Gate: session inactive -> ignore (chan=%s parent=%s)", session_channel_id, parent_channel_id)
        #    return
        # otherwise, proceed forever

        # Vivian - under Callie's advice commenting this out for now
        # Sessions do NOT auto-expire. Only explicit /callie stop closes them.
        # Auto-expire
        #if st.last_activity and (now_epoch() - st.last_activity) > ((await cfg.session_ttl_minutes()) * 60):
        #    log.info("Gate: TTL expired -> auto-stop session")
        #    st.is_active = False
        #    st.ambient = (await cfg.ambient_default())
        #    await self.store.set_session(st)
        #    return    




        # Supposing we're still open, let's update last touched time for the session/channel.
        # Vivian - I was told to comment this out for now
        #st.touch(now_epoch())
        #await self.store.set_session(st)

        # Policy: reply behavior (Ambient vs Mention) is orthogonal to enrichment (Full/Minimal/Anon).
        #reply_policy = await cfg.reply_policy()
        #ambient_mode = reply_policy == "ambient"



        # Vivian - Commented because we feel like this was done in compute_access_decision already
        # invoked = is_invocation(message, self.user) if self.user is not None else False
        # should_respond = invoked or (ambient_mode and st.is_active)

        # TODO we may need to move this into compute_access_decision
        # Quiet mode: suppress ambient replies until ignore_until expires.
        #if (not invoked) and ambient_mode and getattr(st, "ignore_until", 0) and now_epoch() < int(st.ignore_until):
        #    should_respond = False

        # BEGIN REGION --- This is checking for ambient replies ---

        # Ambient safety: optionally ignore messages that are replies to other users (not Callie).
        # This is NOT the same as mentions. Only applies when ambient would otherwise respond.
        #if ambient_mode and not invoked:
        #    if await should_suppress_ambient_reply(
        #        message,
        #        bot_user=self.user,
        #        suppress_enabled=await cfg.suppress_ambient_replies(),
        #        allow_name_prefix=await cfg.allow_name_prefix(),
        #        bot_names=await cfg.callie_aliases(),
        #    ):
        #        log.info("Gate: ambient reply suppression triggered -> ignore")
        #        return

        #if not should_respond:
        #    ignore_until = int(getattr(st, "ignore_until", 0) or 0)
        #    quiet_block = (not invoked) and ambient_mode and ignore_until and now_epoch() < ignore_until
        #    log.info(
        #        "Gate: invoked=%s reply_policy=%s ambient_mode=%s session_active=%s "
        #        "quiet_block=%s ignore_until=%s now=%s suppress_ambient_replies=%s",
        #        invoked, reply_policy, ambient_mode, st.is_active,
        #        quiet_block, ignore_until, now_epoch(),
        #        await cfg.suppress_ambient_replies(),
        #    )
        #    return
        #else:
        #    log.info(f"Gate: proceeding to build response; should_respond={should_respond} invoked={invoked} reply_policy={reply_policy} enrich_policy={enrich_policy}")

        # END REGION --- This is checking for ambient replies ---
        # END Vivian

        #st.last_activity = now_epoch()
        #await self.store.set_session(st)


        await self._prepare_transcript_with_summaries(message, cfg)

        #all_transcript = await self.store.recent_messages(message.channel.id, (await cfg.context_messages()))
        #
        ## --- Summary / context budget configuration
        #summary_enabled = await cfg.summary_enabled()
        #summary_trigger_dropped = await cfg.summary_trigger_dropped_min_messages()
        #summary_batch_min = await cfg.summary_batch_min_messages()
        #summary_batch_max = await cfg.summary_batch_max_messages()
        #summary_batch_max_chars = await cfg.summary_batch_max_chars()
        #summary_min_interval = await cfg.summary_min_interval_seconds()
        #summary_target_max_tokens = await cfg.summary_target_max_tokens()
        #summary_max_loops = await cfg.summary_max_loops()
        ##summary_ctx_note = ""
        #memory_newest = await cfg.memory_newest()
        #memory_oldest = await cfg.memory_oldest()
        #memory_random = await cfg.memory_random()
        #memory_blob = await self.store.get_memory_blob(
        #    newest=memory_newest,
        #    oldest=memory_oldest,
        #    random_mid=memory_random
        #)
        ## Reserve room for system prompt + memory + server_ctx + notices + output.
        #reserve = est_tokens(await cfg.system_prompt()) + est_tokens(memory_blob) + (await cfg.summary_target_max_tokens()) + 400
        #transcript_budget = max(1200, (await cfg.context_token_limit()) - reserve)
        #
        #def _filter_visible_for_prompt(rows: List[dict]) -> List[dict]:
        #    # Once a raw message is summarized, it should stop showing up as raw history.
        #    out: List[dict] = []
        #    for mm in rows:
        #        if mm.get("is_summary"):
        #            out.append(mm)
        #            continue
        #        if mm.get("is_summarized"):
        #            continue
        #        out.append(mm)
        #    return out
        #
        ## 1) Compute what *would* be dropped (but do not drop yet).
        #visible = _filter_visible_for_prompt(all_transcript)
        #transcript, dropped_msgs, kept_tokens = build_trimmed_transcript(visible, transcript_budget)
        #would_drop = len(dropped_msgs)
        #
        #if would_drop:
        #    log.info(f"CTX pre-summary: would_drop={would_drop} kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")
        #else:
        #    log.info(f"CTX pre-summary: ok kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")
        #
        ## 2) If enough would be dropped, summarize *those* messages first, then recompute.
        #did_summary = False
        #summarized_n = 0
        #try:
        #    total_summarized = 0
        #    loops = max(1, int(summary_max_loops or 0))
        #    for loop_i in range(loops):
        #        if not (summary_enabled and would_drop >= summary_trigger_dropped):
        #            break
        #
        #        # On the first loop, respect SUMMARY_MIN_INTERVAL_SECONDS; on subsequent loops within this same
        #        # message, allow additional summaries so we can drain a backlog.
        #        if loop_i == 0:
        #            last_sum = await self.store.most_recent_summary_time(int(message.channel.id))
        #            if (now_epoch() - int(last_sum or 0)) < summary_min_interval:
        #                break
        #
        #        dropped_ids = [m.get("db_id") for m in dropped_msgs if m.get("db_id")]
        #        #dropped_list = list(dropped_ids)
        #        batch = await self.store.unsummarized_dropped_messages(int(message.channel.id), cast(List[int], dropped_ids), summary_batch_max)
        #        if not batch:
        #            break
        #
        #        emergency = (would_drop >= (summary_trigger_dropped * 2))
        #        if len(batch) < summary_batch_min and not emergency:
        #            break
        #
        #        total_chars = 0
        #        trimmed_batch: List[dict] = []
        #        for mm in batch:
        #            total_chars += len(mm.get("content", "") or "")
        #            trimmed_batch.append(mm)
        #            if total_chars >= summary_batch_max_chars:
        #                break
        #
        #        if not trimmed_batch:
        #            break
        #
        #        summary_text = await summarize_messages_block(trimmed_batch, await cfg.openai_model(), summary_target_max_tokens, api_key=await cfg.openai_api_key())
        #        if not summary_text:
        #            break
        #
        #        start_db = int(trimmed_batch[0]["db_id"])
        #        end_db = int(trimmed_batch[-1]["db_id"])
        #        start_ts = int(trimmed_batch[0]["created_at"])
        #        end_ts = int(trimmed_batch[-1]["created_at"])
        #        participants = [m.get("author_name", "") for m in trimmed_batch]
        #        await self.store.insert_summary_and_mark(
        #            int(message.channel.id),
        #            summary_text,
        #            start_db,
        #            end_db,
        #            start_ts,
        #            end_ts,
        #            participants,
        #        )
        #
        #        did_summary = True
        #        total_summarized += len(trimmed_batch)
        #
        #        # Recompute trim after those raws are hidden before the next loop.
        #        all_transcript = await self.store.recent_messages(message.channel.id, (await cfg.context_messages()))
        #        visible = _filter_visible_for_prompt(all_transcript)
        #        transcript, dropped_msgs, kept_tokens = build_trimmed_transcript(visible, transcript_budget)
        #        would_drop = len(dropped_msgs)
        #
        #        log.info(
        #            f"CTX post-summary[{loop_i+1}/{loops}]: summarized_batch={len(trimmed_batch)} "
        #            f"would_drop_now={would_drop} kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}"
        #        )
        #
        #        if would_drop < summary_trigger_dropped:
        #            break
        #
        #    if did_summary:
        #        summarized_n = total_summarized
        #        summary_ctx_note = f"(Context note: I summarized {summarized_n} older message(s) into a stored summary to save context.)"
        #except Exception as e:
        #    log.error(f"Summarization step failed (non-fatal): {e}")
        #
        ## Final drop-count after (possible) summarization.
        #dropped_count = len(dropped_msgs)
        #if dropped_count:
        #    log.info(f"CTX trim: dropped_msgs={dropped_count} kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")
        #else:
        #    log.info(f"CTX ok: kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")




        # Vivian TODO - commenting out for now
        # Session / policy context for the model (not user-provided).
        #try:
        #    server_ctx += (
        #        "\n\n[Policy]\n"
        #        + f"reply_policy={reply_policy} (ambient={'ON' if ambient_mode else 'OFF'})\n"
        #        + f"msg_enrich_policy={enrich_policy}\n"
        #        + f"require_callie_role={require_callie_role}\n"
        #    )
        #except Exception:
        #    pass
