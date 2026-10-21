"""Fail any test that opens a network connection (#66: no live calls in CI)."""

import socket

import pytest


def _refuse(*args, **kwargs):
    raise RuntimeError("a test tried to open a network connection")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
