    def _build_model_input_parts(
        self,
        *,
        user_text: str,
        system_preamble: Optional[str] = None,
        attachment_parts: Optional[List[Dict[str, Any]]] = None,
        connector_notes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build the 'content parts' list for a single user message.
        Keeps message assembly consistent and testable.

        Content parts follow the common OpenAI schema style:
          - {"type": "input_text", "text": "..."}
          - {"type": "input_image", "image_url": "data:image/png;base64,..."}
          - {"type": "input_file", "filename": "...", "file_data": "data:application/pdf;base64,..."}
        """

        parts: List[Dict[str, Any]] = []

        if system_preamble:
            parts.append({"type": "input_text", "text": system_preamble})

        # Always include the user message text
        parts.append({"type": "input_text", "text": user_text})

        # Add any attachment-derived parts (images/files + any connector notes you already included there)
        if attachment_parts:
            parts.extend(attachment_parts)

        # Optional extra notes (if you want them separate from attachment handling)
        if connector_notes:
            parts.append({"type": "input_text", "text": "Connector note: " + " | ".join(connector_notes)})

        return parts

    async def _send_to_model(
        self,
        *,
        cfg: "GuildConfig",
        message: "discord.Message",
        transcript: str,
        input_parts: List[Dict[str, Any]],
        invoked: bool,
        response_style_hint: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """
        One place that knows how to call OpenAI with your project's conventions.
        Returns (reply_text, response_id).

        This function should be the only thing that touches your openai_helpers layer
        from on_message(), so changes to payload format are localized.
        """

        # Pull all knobs from cfg (or global config) here so on_message stays lean.
        api_key = await cfg.openai_api_key()
        model = await cfg.openai_model()  # or however you store it
        # TODO implement temperature per-guild
        temperature = await cfg.openai_temperature()
        max_output_tokens = await cfg.max_output_tokens()

        # Whatever "context" you pass (recent messages, summaries, guild metadata, etc.)
        # Keep it here, not in on_message.
        guild_ctx = {
            "guild_id": getattr(message.guild, "id", None),
            "channel_id": getattr(message.channel, "id", None),
            "author_id": getattr(message.author, "id", None),
            "invoked": invoked,
        }

        # Many wrappers take something like:
        #   openai_respond(model, api_key, transcript, input_parts, **opts)
        # If yours is different, adapt only HERE.
        reply_text, response_id = await openai_respond(
            api_key=api_key,
            model=model,
            transcript=transcript,
            input_parts=input_parts,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            guild_ctx=guild_ctx,
            response_style_hint=response_style_hint,
        )

        return reply_text, response_id
