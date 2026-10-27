from collections.abc import Iterable, Sequence


class RequestVoteRequest:
    term: int
    candidate_id: str
    last_log_index: int
    last_log_term: int

    def __init__(
        self,
        *,
        term: int = ...,
        candidate_id: str = ...,
        last_log_index: int = ...,
        last_log_term: int = ...,
    ) -> None: ...


class RequestVoteResponse:
    term: int
    vote_granted: bool

    def __init__(self, *, term: int = ..., vote_granted: bool = ...) -> None: ...


class LogEntry:
    index: int
    term: int
    command_json: str

    def __init__(
        self,
        *,
        index: int = ...,
        term: int = ...,
        command_json: str = ...,
    ) -> None: ...


class AppendEntriesRequest:
    term: int
    leader_id: str
    previous_log_index: int
    previous_log_term: int
    entries: Sequence[LogEntry]
    leader_commit: int

    def __init__(
        self,
        *,
        term: int = ...,
        leader_id: str = ...,
        previous_log_index: int = ...,
        previous_log_term: int = ...,
        entries: Iterable[LogEntry] = ...,
        leader_commit: int = ...,
    ) -> None: ...


class AppendEntriesResponse:
    term: int
    success: bool
    match_index: int
    conflict_index: int

    def __init__(
        self,
        *,
        term: int = ...,
        success: bool = ...,
        match_index: int = ...,
        conflict_index: int = ...,
    ) -> None: ...


class ProposeRequest:
    operation_json: str

    def __init__(self, *, operation_json: str = ...) -> None: ...


class ProposeResponse:
    accepted: bool
    committed: bool
    term: int
    index: int
    leader_id: str
    error: str

    def __init__(
        self,
        *,
        accepted: bool = ...,
        committed: bool = ...,
        term: int = ...,
        index: int = ...,
        leader_id: str = ...,
        error: str = ...,
    ) -> None: ...


class GetStatusRequest:
    def __init__(self) -> None: ...


class NodeStatus:
    node_id: str
    role: str
    term: int
    leader_id: str
    commit_index: int
    last_applied: int
    last_log_index: int
    last_log_term: int
    heartbeat_age_ms: int
    recent_entries: Sequence[LogEntry]

    def __init__(
        self,
        *,
        node_id: str = ...,
        role: str = ...,
        term: int = ...,
        leader_id: str = ...,
        commit_index: int = ...,
        last_applied: int = ...,
        last_log_index: int = ...,
        last_log_term: int = ...,
        heartbeat_age_ms: int = ...,
        recent_entries: Iterable[LogEntry] = ...,
    ) -> None: ...
