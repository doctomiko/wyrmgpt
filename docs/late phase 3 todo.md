* THIS IS DONE 3/10: First, finish the query settings/UI truth so global and project behavior are equally editable. In the current build, that query settings section still appears to live inside the project settings block in the HTML, so global editing is probably still structurally wrong unless you fixed it after this zip. That’s a small but real cleanup item.

Second, make the include/expand collector fully honest for files too. Right now you’ve got caps and diagnostics for files, memories, and chats, but the “all scoped files” path still smells like it is being handled through the older file-message path rather than one perfectly unified collector with per-kind caps enforced symmetrically. It works, but it is not yet as conceptually clean as memories and chats.

Third, conversation summaries are still undercooked in the Phase 3 sense. The docs wanted project-other-conversation summaries to be the default light-weight representation, with full transcripts only when justified. You’ve got transcript artifacts and summaries in the system, but I don’t think you’ve fully completed the “other conversations in same project default to summaries” policy yet. That’s still an open piece of 3C/3D. The remaining design explicitly calls for conversation summary suggestions and default project-wide summary use rather than auto-including every full transcript. 

wyrmgpt_corpus_rag_vision_spec

Fourth, conversation-window expansion is still missing. Right now your expansion logic can promote whole FILE/MEMORY/CHAT artifacts, but the original 3C target also included “give me a local window around the matching chat section,” which is often better than expanding a whole transcript. That’s still not there. The design calls out include_conversation_window(...) as a separate expansion action. 

wyrmgpt_corpus_rag_vision_spec

Fifth, embeddings/vector retrieval is still aspirational. You have the flag, the config, and the UI vocabulary, but the actual retrieval code still looks FTS-only. That’s okay — the design explicitly treats embeddings/reranking as later — but it does mean EMBEDDING is not truly done yet. The RAG vision doc is pretty explicit that embeddings and reranking are post-MVP additions, not part of the first completed pass.

Sixth, memory workflow is still not fully “mature” by your own spec. You’ve got create/edit/delete and scope promotion, which is the important part. But the full 3E wish-list still included archived toggle, pinned toggle, move/copy UI, richer filter/search, and a more complete artifact debug surface. Those are not blockers to saying Phase 3 mostly works, but they are still unfinished Phase 3 polish. The remaining design explicitly lists move/copy/archive/pinned/search/filter as part of the memory management end state. 

wyrmgpt_corpus_rag_vision_spec

* THIS IS DONE 3/10: Seventh, there’s still some diagnostic cleanup and truthfulness work. The context panel is much better now, but the next refinement is to make every section reflect exactly one conceptual layer: scope/query, prompt layers, whole assets, RAG final, RAG raw, RAG expansion, recent history. That’s mostly UX polish now, not architecture.

So the blunt summary is:

You are out of the “can we make this work at all?” phase.

What remains is:
finish summary-aware conversation enrichment,
finish smarter expansion shapes like conversation windows,
finish true vector retrieval,
finish the last 20% of settings/UI truth,
and polish the memory management controls to match the original grown-up spec.

If I were steering the ship from here, I would do:
conversation summaries + conversation-window expansion next,
then vector retrieval,
then the remaining memory/personalization polish.

That’s the straightest line to saying “Phase 3 is actually done” instead of “Phase 3 basically works if you squint hard enough.”