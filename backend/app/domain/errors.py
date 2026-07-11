class TameInkError(Exception):
    code = "TAME_INK_ERROR"


class InvalidProjectIdError(TameInkError):
    code = "INVALID_PROJECT_ID"


class WorkspacePathViolationError(TameInkError):
    code = "WORKSPACE_PATH_VIOLATION"


class CanonContentError(TameInkError):
    code = "SCHEMA_VALIDATION_FAILED"


class SearchQueryError(TameInkError):
    code = "SEARCH_QUERY_INVALID"


class CanonVersionConflictError(TameInkError):
    code = "CANON_VERSION_CONFLICT"


class StorageWriteError(TameInkError):
    code = "STORAGE_WRITE_FAILED"


class StorageReadError(TameInkError):
    code = "STORAGE_READ_FAILED"


class RecoveryIncompleteError(TameInkError):
    code = "RECOVERY_INCOMPLETE"
