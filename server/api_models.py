# -------------------------
# API Contracts
# -------------------------

from typing import Optional
from pydantic import BaseModel

# region API Contracts (class definitions)

class AppConfigUpdateRequest(BaseModel):
    search_chat_history: Optional[bool] = None

class QuerySettingsUpdateRequest(BaseModel):
    scope_type: str = "global"
    scope_id: str = ""
    query_include: str | None = None
    query_expand_results: str | None = None
    query_max_full_files: int | None = None
    query_max_full_memories: int | None = None
    query_max_full_chats: int | None = None
    query_expand_min_artifact_hits: int | None = None
    query_expand_chat_window_before: int | None = None
    query_expand_chat_window_after: int | None = None

class ModelSettingsUpdateRequest(BaseModel):
    scope_type: str = "global"
    scope_id: str = ""
    temperature: float | None = None
    thinking_level: int | None = None
    show_thinking: bool | None = None
    verbosity: int | None = None
    tool_aggressiveness: int | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None

class FileDescriptionUpdate(BaseModel):
    description: str | None = None

class FileRenameRequest(BaseModel):
    name: str

class FileImageDescribeRequest(BaseModel):
    deployment_id: str | None = None
    overwrite: bool = True


class FileImageOcrRequest(BaseModel):
    deployment_id: str | None = None
    overwrite: bool = True

class FileMoveScopeRequest(BaseModel):
    scope_type: str
    scope_id: int | None = None
    scope_uuid: str | None = None

class BulkFileMoveScopeRequest(BaseModel):
    file_ids: list[str]
    scope_type: str
    scope_id: int | None = None
    scope_uuid: str | None = None

class BulkFileDeleteRequest(BaseModel):
    file_ids: list[str]


class ArtifactMoveScopeRequest(BaseModel):
    scope_type: str
    scope_id: int | None = None
    scope_uuid: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: str | None = None
    system_prompt: str | None = None
    override_core_prompt: bool | None = None
    default_advanced_mode: bool | None = None

class TitleRequest(BaseModel):
    title: str

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    message: str

class ABChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    model_a: Optional[str] = None
    model_b: Optional[str] = None
    message: str

class ABCanonicalRequest(BaseModel):
    conversation_id: str
    ab_group: str
    slot: str  # "A" or "B"

class MemoryCreate(BaseModel):
    content: str
    importance: int = 0
    tags: str | None = None
    created_by: str = "user"
    origin_kind: str = "user_asserted"
    scope_type: str = "global"
    scope_id: int | None = None
    persona_id: str | None = None
    persona_ids: list[str] | None = None
    persona_scope: str | None = None
    persona_context_mode: str = "include"

class MemoryUpdate(BaseModel):
    content: str
    importance: int = 0
    tags: str | None = None
    created_by: str = "user"
    origin_kind: str = "user_asserted"
    scope_type: str | None = None
    scope_id: int | None = None
    persona_id: str | None = None
    persona_ids: list[str] | None = None
    persona_scope: str | None = None
    persona_context_mode: str | None = None

class PinRequest(BaseModel):
    text: str
    pin_kind: str | None = None
    title: str | None = None
    scope_type: str | None = None
    scope_id: int | None = None

class AboutYouRequest(BaseModel):
    nickname: str = ""
    age: str = ""
    occupation: str = ""
    more_about_you: str = ""

class FileRegister(BaseModel):
    name: str
    path: str
    mime_type: str | None

class ArtifactCreate(BaseModel):
    name: str
    content: str
    tags: str | None = None

class ImportRule(BaseModel):
    include_tags: str | None = None
    exclude_tags: str | None = None
    include_artifact_ids: str | None = None  # JSON

class NewChatResponse(BaseModel):
    conversation_id: str

class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str | None = None
    visibility: str = "private"
    override_core_prompt: bool = False
    default_advanced_mode: bool = False

class MoveProjectRequest(BaseModel):
    project_id: Optional[int] = None
    project_name: Optional[str] = None

class MemoryLinkProjectRequest(BaseModel):
    project_id: Optional[int] = None
    project_name: Optional[str] = None

class ArchiveRequest(BaseModel):
    archived: bool = True

class CorpusSearchRequest(BaseModel):
    conversation_id: str
    query: str
    limit: int = 10
    include_global: bool = False
    principal_type: str = "user"
    principal_id: str = "local"
    tenant_id: str = "default"
    admin_view: str | None = None

class FilePreflightItem(BaseModel):
    name: str
    sha256: str
    scope_type: str
    conversation_id: str | None = None
    project_id: int | None = None

class FilePreflightRequest(BaseModel):
    files: list[FilePreflightItem]

# endregion
