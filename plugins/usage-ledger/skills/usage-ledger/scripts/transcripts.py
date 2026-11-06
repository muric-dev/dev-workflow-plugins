"""Step 2. Claude Code transcripts -> questions.

Input: ~/.claude/projects/<encoded path>/<session>.jsonl, plus the subagent
transcripts in <session>/subagents/**/*.jsonl.

Output: {question_id: question}, where a question is
    {"id", "session", "asked_at", "stamps": [datetime], "turn_ms": int,
     "calls": {message_id: assistant line}, "tools": {tool name}}

A question starts at each human prompt in the main transcript. Every later line,
from the main transcript or a subagent, belongs to it until the next prompt.

This is the only module that knows the transcript format. If Claude Code changes
it, fix it here.
"""
import json
import re

from common import config_dir, parse_ts
from project import in_project


def encode_path(path):
    """Claude Code names each project's transcript folder after its path like this."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def transcript_dirs(paths):
    base = config_dir() / "projects"
    if not base.is_dir():
        return []
    dirs = [entry for entry in base.iterdir() if entry.is_dir()]
    prefixes = tuple(encode_path(path) for path in paths)
    # Folder names are lossy, so with no match every folder is scanned and the cwd filter decides.
    return [entry for entry in dirs if entry.name.startswith(prefixes)] or dirs


def iter_lines(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if isinstance(line, dict):
                yield line


def read_session(files, paths):
    """Lines of one session in time order, as (line, is_from_main_transcript)."""
    lines = []
    for index, path in enumerate(files):
        for line in iter_lines(path):
            cwd = line.get("cwd")
            if line.get("timestamp") and (not cwd or in_project(cwd, paths)):
                lines.append((line, index == 0))
    lines.sort(key=lambda item: item[0]["timestamp"])
    return lines


def is_call(line):
    """An assistant line that a model was billed for."""
    message = line.get("message")
    return (
        line.get("type") == "assistant"
        and isinstance(message, dict)
        and bool(message.get("id"))
        and isinstance(message.get("usage"), dict)
        and message.get("model") != "<synthetic>"
    )


def has_typed_text(line):
    if line.get("isMeta") or line.get("isCompactSummary") or line.get("toolUseResult"):
        return False
    content = (line.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "text" for block in content
    )


def is_prompt(line, has_origin):
    """A line the user typed. Older transcripts have no `origin`, so text content decides."""
    if line.get("type") != "user" or line.get("isSidechain") or not line.get("uuid"):
        return False
    if has_origin:
        origin = line.get("origin")
        return isinstance(origin, dict) and origin.get("kind") == "human"
    return has_typed_text(line)


def new_question(question_id, session, asked_at):
    return {
        "id": question_id,
        "session": session,
        "asked_at": asked_at,
        "stamps": [],
        "turn_ms": 0,
        "calls": {},
        "tools": set(),
    }


def tool_names(line):
    """Names of the tools an assistant line called. Names only, never their input."""
    content = (line.get("message") or {}).get("content")
    if line.get("type") != "assistant" or not isinstance(content, list):
        return set()
    return {block["name"] for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("name"), str)}


def split_questions(lines, session):
    has_origin = any(isinstance(line.get("origin"), dict) for line, _ in lines)
    questions = []
    current = None
    for line, is_main in lines:
        if is_main and is_prompt(line, has_origin):
            question_id = line.get("promptId") or line["uuid"]
            if current is None or current["id"] != question_id:
                current = new_question(question_id, session, line["timestamp"])
                questions.append(current)
        elif current is None:
            if not is_call(line):
                continue
            # Calls before any prompt (headless runs) become a question named after the session.
            current = new_question(session, session, line["timestamp"])
            questions.append(current)
        current["stamps"].append(parse_ts(line["timestamp"]))
        # Every line of a message counts here: each one may hold a different content block.
        current["tools"] |= tool_names(line)
        if is_call(line):
            # A message is logged once per content block: the last line has the final usage.
            current["calls"][line["message"]["id"]] = line
        if line.get("subtype") == "turn_duration":
            current["turn_ms"] += line.get("durationMs") or 0
    return questions


def read_questions(paths, only_session=None):
    sessions = []
    for directory in transcript_dirs(paths):
        for main in directory.glob("*.jsonl"):
            if only_session and main.stem != only_session:
                continue
            files = [main, *sorted((directory / main.stem / "subagents").rglob("*.jsonl"))]
            lines = read_session(files, paths)
            if lines:
                sessions.append((lines[0][0]["timestamp"], main.stem, lines))
    # Oldest session first, so a resumed session's copied calls count only in the original.
    seen = set()
    questions = {}
    for _, session, lines in sorted(sessions, key=lambda item: item[:2]):
        for question in split_questions(lines, session):
            fresh = {key: line for key, line in question["calls"].items() if key not in seen}
            seen.update(fresh)
            question["calls"] = fresh
            target = questions.setdefault(question["id"], question)
            target["calls"].update(fresh)
            target["tools"] |= question["tools"]
    return questions
