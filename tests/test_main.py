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


def test_arduino_commands_follow_meaningful_motion_states():
    class DummySerial:
        def __init__(self):
            self.is_open = True
            self.sent = []

        def write(self, data):
            self.sent.append(data.decode("utf-8").strip())
            return len(data)

        def flush(self):
            return None

    arduino = module.ControleArduino.__new__(module.ControleArduino)
    arduino.conexao = DummySerial()

    arduino.levantar_braco()
    arduino.piscar_alerta_queda()
    arduino.desligar_alerta_queda()

    assert arduino.conexao.sent == ["INICIAR", "AJUDA", "RESETAR"]


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


def test_listen_once_falls_back_to_local_recognition(monkeypatch):
    class DummyRecognizer:
        def __init__(self):
            self.calls = []

        def listen(self, microphone, timeout, phrase_time_limit):
            return object()

        def recognize_google(self, audio, language):
            raise module.sr.RequestError("timeout")

    class DummyAudio:
        def get_wav_data(self, **kwargs):
            return b"audio"

    assistant = object.__new__(module.NovaAssistant)
    assistant.recognizer = DummyRecognizer()
    assistant.local_model = object()

    captured = {}

    def mock_local(audio):
        captured["called"] = True
        return "nova que horas sao"

    monkeypatch.setattr(assistant, "_recognize_local_audio", mock_local)

    result = assistant.listen_once(object(), timeout=1, phrase_time_limit=1)

    assert result == "nova que horas sao"
    assert captured["called"] is True


def test_start_monitors_skips_when_camera_is_missing(monkeypatch):
    assistant = object.__new__(module.NovaAssistant)
    assistant.monitor_threads = []
    assistant.monitor_stop = module.threading.Event()
    assistant.camera_paused = module.threading.Event()

    monkeypatch.setattr(module.NovaAssistant, "choose_camera_index", lambda self: None)

    assistant.start_monitors()

    assert assistant.monitor_threads == []


def test_encontrar_porta_arduino_respects_explicit_port(monkeypatch):
    calls = []

    class FakeSerial:
        def __init__(self, port, baudrate, timeout):
            calls.append((port, baudrate, timeout))
            if port != "COM9":
                raise module.serial.SerialException("wrong port")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(module.serial, "Serial", FakeSerial)
    monkeypatch.setattr(module.list_ports, "comports", lambda: [type("Port", (), {"device": "COM4"})()])

    assert module.encontrar_porta_arduino("COM9") == "COM9"
    assert calls[0] == ("COM9", 9600, 0.2)


def test_process_safety_events_triggers_arduino_alert():
    assistant = object.__new__(module.NovaAssistant)
    assistant.safety_events = module.queue.Queue()
    assistant.pending_fall_response = False
    assistant.fall_response_deadline = 0.0
    assistant.respond = lambda text: None
    assistant.arduino = type("DummyArduino", (), {"piscar_alerta_queda": lambda self: calls.append("alert")})()
    calls = []
    assistant.safety_events.put("fall")

    assistant.process_safety_events()

    assert assistant.pending_fall_response is True
    assert calls == ["alert"]


def test_main_starts_camera_monitor_only_after_pir_detection(monkeypatch):
    class DummyArduino:
        def __init__(self):
            self.calls = []

        def esperar_presenca(self, timeout_segundos=10.0):
            self.calls.append(timeout_segundos)
            return True

        def levantar_braco(self):
            return None

        def abaixar_braco(self):
            return None

        def desligar_alerta_queda(self):
            return None

        def fechar(self):
            return None

    class DummyNova:
        def __init__(self):
            self.start_calls = 0
            self.arduino = None

        def start_monitors(self):
            self.start_calls += 1

        def run(self):
            return None

    dummy_arduino = DummyArduino()
    dummy_nova = DummyNova()

    monkeypatch.setattr(module, "encontrar_porta_arduino", lambda value="": "COM9")
    monkeypatch.setattr(module, "ControleArduino", lambda port: dummy_arduino)
    monkeypatch.setattr(module, "NovaAssistant", lambda: dummy_nova)

    module.main()

    assert dummy_nova.start_calls == 1


def test_fall_answer_pauses_camera_until_new_pir_motion(monkeypatch):
    assistant = object.__new__(module.NovaAssistant)
    assistant.pending_fall_response = True
    assistant.camera_paused = module.threading.Event()
    assistant.camera_paused.clear()
    assistant.arduino = type("DummyArduino", (), {"esperar_presenca": lambda self, timeout_segundos=10.0: True})()
    assistant.respond = lambda text: None

    captured = {}

    def fake_pause(self, seconds=60.0):
        captured["pause_seconds"] = seconds
        self.camera_paused.set()

    monkeypatch.setattr(module.NovaAssistant, "_pause_camera_after_fall_answer", fake_pause)
    assistant.handle_fall_answer("estou bem")

    assert assistant.pending_fall_response is False
    assert assistant.camera_paused.is_set() is True
    assert captured["pause_seconds"] == 60.0
