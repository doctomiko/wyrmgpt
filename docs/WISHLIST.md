ALREADY DONE:
* DONE Provider / deployments for Claude and Gemini - because what good is a test tool that has nothing to test against.
* DONE Web search: probably implemented as a bot-callable tool.
* DONE Scaffold cards that show up in real-time instead of waiting for the page to be rebuild after chat response.

TOP OF THE LIST:
* Heat knobs and CoT tooling/visibility
* Ability to export the database in as a series of JSON files.
* Unit tests, so we can tell if we broke something.
* Other bells and whistles that fell out of the basket along the way, like
  - 3A.5
  - AI assisted RAG Query expansion
  - Automatic PDF OCR scanning as needed
  - See also: Not_Done_Yet.md
* Maybe streamline our first-time-run processes so that they will just work for newbies with fewer instructions. * And maybe a Docker container deployment.

BEYOND THAT:
* The structure to let parts of the Callie connector use it as an API.
* Maybe a cron job (or similar background process) to handle the routine index/vector jobs and stuff.
* Read aloud and voice recorder modes
* It is debatable if we need to be able to create sandboxes, unzip files, generate images, or write code in Python. Those would be sexy features sure:
  - Code sandbox .venv
  - ZIP extraction
  - Image gen
* If we're going there, maybe eventually access to GitHub repos are a user who can't make anything permanent on their own.