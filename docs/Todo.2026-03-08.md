# Cool things our app can do (so far)

* Chat with two different models at the same time and compare results. Heck, you can try talking to the same model in both A and B channels to see if it is variable.
* AB mode lets you decide which response is the one you want to keep in the canon conversation context. Change that at any time during your chat session.
* You can export a Markdown transcript of any chat conversation.
* Move files between chat, project, and global scope easily.
* See exactly what is being sent to LLM context every time and even before you hit Send.
* Your chat history and files live on your computer. The only time that data leaves is if you send your chats to a cloud-based API.
* The UI is super-fast and effecient. It will not bog down on long chat sessions that go on for days or weeks.
* We provide a cost table for the available models. Pick what works best for you.
* Add as many memories and files as you want, without limits.
* Chat navigation includes dynamic summaries and titles, so you have some clue what the chat was about.
* Chat messages include a zeitgeber (time-giver) hint for the bot, so your AI assistant understands when you sent a specific message, even if the API doesn't support it.
* You can dynamically pick the model even mistream during your conversation.
* Can read MS Word (docx), PDF, markdown, various source code, and image files (on OpenAI models).

# Things we need to do yet:

* Start treating memory text the same way I am treating files and chat transcripts, by stuffing it into the artifactor and chunking them if they're really big. That'd mean that a memory could be potentially something as big as let's say one of Alara's 20,000 word short stories and it could still be accessible to the bot as if it remembered reading the whole thing – effectively the same as files are now (though really big PDF do get truncated for sanity).
* Upload an OpenAI export into this database and have all your past chat history and projects appear on your own PC as if you'd never lost them. Ideally, you could get a future export and do-over and it would not have any negative impact. Once this is done, the corpus that RAG can search will be MUCH larger and better chances the bot may find things to remember and comment on.
* Switch from FTS+BM25 to a vector DB / embeddings engine. We can (and should) do both but this would greatly augment the LLMs sense of recollection without having to be trained.
* Web URL scraping and web search as things that need to be done to make the bots RetroLM/RAG more relevant in the real world.
* And ultimately we need to be able to move to locally hosted LLMs and non-OpenAI alternatives. This should not be all that hard to implement.
* Ability for the bot to engage with toolkits that expand its capabilities.
* Want to make it possible to use this as an API for the backend of the Discord connector.