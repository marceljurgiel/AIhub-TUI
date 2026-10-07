"""wants_tools: when plain chat offers tools to the model."""
from __future__ import annotations

import pytest

from aihub.tools import wants_tools


def _ask(text):
    return wants_tools([{"role": "system", "content": "s"}, {"role": "user", "content": text}])


@pytest.mark.parametrize("text", [
    "I'm running late today, cheer me up",       # "run" inside "running"
    "what is 2/3 as a decimal?",                 # a slash that isn't a path
    "explain and/or logic",
    "give me a list of 5 fruits",                # "list" as a noun
    "write a poem about autumn",
    "read me a bedtime story",
    "create a workout plan for beginners",
    "what's the difference between a list and a tuple in python?",
    "what does 'execute' mean in law?",
    "how does http work?",
    "napisz wiersz o jesieni",
])
def test_ordinary_conversation_gets_no_tools(text):
    assert not _ask(text)


@pytest.mark.parametrize("text", [
    "read the file ~/notes.txt",
    "list files in ./src",
    "what's in /etc/hostname?",
    "show me the contents of README.md",
    "run ls -la",
    "execute the test suite",
    "run `npm test`",
    "check git status",
    "git log -5",
    "fetch https://example.com and summarize it",
    "search the web for the latest rust release",
    "what's the weather in Warsaw today?",
    "how much disk space is free?",
    "przeczytaj plik notatki.txt",
    "uruchom testy",
    "wyszukaj w internecie najnowsze wiadomości",
    "jaka jest dziś pogoda w Lizbonie?",
])
def test_tool_requests_get_tools(text):
    assert _ask(text)


def test_follow_up_after_tool_use_keeps_tools():
    history = [
        {"role": "user", "content": "read notes.txt"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file", "arguments": {"path": "notes.txt"}}}]},
        {"role": "tool", "content": "...", "tool_call_id": "c1"},
        {"role": "assistant", "content": "It lists three tasks. Want the next one too?"},
        {"role": "user", "content": "yes please"},
    ]
    assert wants_tools(history)


def test_follow_up_only_looks_at_the_previous_exchange():
    history = [
        {"role": "user", "content": "read notes.txt"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "read_file"}}]},
        {"role": "tool", "content": "...", "tool_call_id": "c1"},
        {"role": "assistant", "content": "Done."},
        {"role": "user", "content": "thanks! unrelated: tell me a joke"},
        {"role": "assistant", "content": "Why did the chicken..."},
        {"role": "user", "content": "haha, another one"},
    ]
    assert not wants_tools(history)


def test_no_user_message():
    assert not wants_tools([{"role": "system", "content": "s"}])
