from server.db import db_refresh_conversation_transcript_artifact
import traceback

cid = "oaiexport-69482d92-6e10-8327-ac11-9096f87840c6"
try:
    print(db_refresh_conversation_transcript_artifact(cid, force_full=True, reason="debug-single-failure"))
except Exception:
    traceback.print_exc()