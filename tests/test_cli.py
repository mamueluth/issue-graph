"""The window opens on the X socket a dev container forwards, even when DISPLAY is empty there."""

import os
import socket

import pytest

from issue_graph import cli


@pytest.fixture
def linux_without_display(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("REMOTE_CONTAINERS_DISPLAY_SOCK", raising=False)


@pytest.fixture
def x_socket(tmp_path):
    path = tmp_path / "X3"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    yield path
    server.close()


def test_forwarded_socket_becomes_the_display(linux_without_display, monkeypatch, x_socket):
    monkeypatch.setenv("REMOTE_CONTAINERS_DISPLAY_SOCK", str(x_socket))
    assert cli.has_display()
    assert os.environ["DISPLAY"] == ":3"


def test_no_display_without_a_forwarded_socket(linux_without_display):
    assert not cli.has_display()


def test_forwarded_path_that_is_no_socket(linux_without_display, monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_CONTAINERS_DISPLAY_SOCK", str(tmp_path / "X0"))
    assert not cli.has_display()
    assert os.environ["DISPLAY"] == ""


def test_a_set_display_stays(linux_without_display, monkeypatch, x_socket):
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setenv("REMOTE_CONTAINERS_DISPLAY_SOCK", str(x_socket))
    assert cli.has_display()
    assert os.environ["DISPLAY"] == ":1"
