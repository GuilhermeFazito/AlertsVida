import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("alertsvida_main", ROOT / "main.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_main_starts_without_arduino(monkeypatch):
    monkeypatch.setenv("NOVA_ARDUINO_PORT", "COM999")
    run_calls = []

    class DummyNova:
        def run(self):
            run_calls.append("run")

    with patch.object(module.serial, "Serial", side_effect=module.serial.SerialException("no port")):
        with patch.object(module, "NovaAssistant", return_value=DummyNova()) as assistant_factory:
            module.main()

    assert assistant_factory.called
    assert run_calls == ["run"]


def test_choose_microphone_index_skips_output_devices(monkeypatch):
    microphone_names = [
        "Microsoft Sound Mapper - Input",
        "Headphones (Realtek HD Audio 2nd output)",
        "Microfone (Realtek Audio)",
        "Stereo Mix (Realtek Audio)",
    ]

    calls = []

    class FakeMicrophone:
        @staticmethod
        def list_microphone_names():
            return microphone_names

        def __init__(self, device_index=None):
            calls.append(device_index)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(module.sr, "Microphone", FakeMicrophone)

    assistant = object.__new__(module.NovaAssistant)
    assert assistant.choose_microphone_index() == 2
    assert calls == [2]
