"""
Nova - Assistente de Voz
========================
Assistente de voz em português com reconhecimento facial, integração com
IA generativa local (Ollama) e suporte a múltiplos comandos de voz.

Dependências: ver requirements.txt
Uso: python main.py
"""

from __future__ import annotations

import ast
import asyncio
import os
import queue
import re
import tempfile
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import pyttsx3
import requests
import serial
import speech_recognition as sr
import win32com.client
from serial.tools import list_ports


class ControleArduino:
    """Controla o Arduino pelo cabo USB."""

    TAXA_SERIAL = 9600

    def __init__(self, porta: str) -> None:
        self.porta = porta
        # Conecta ao Arduino.
        self.conexao = serial.Serial(porta, self.TAXA_SERIAL, timeout=0.5)
        time.sleep(2)

    def esperar_presenca(self, timeout_segundos: float = 10.0) -> bool:
        """Espera o sensor detectar alguém, mas abandona após um tempo limite."""
        print(f"Aguardando o sensor PIR no Arduino ({self.porta}).")
        inicio = time.monotonic()
        while time.monotonic() - inicio < timeout_segundos:
            linha = self.conexao.readline().decode("utf-8", errors="ignore").strip()
            if linha == "PRONTO":
                print("Arduino pronto. Passe em frente ao sensor para iniciar a NOVA.")
            elif linha == "MOVIMENTO":
                print("Presença detectada pelo PIR.")
                return True
        print(f"Arduino na porta {self.porta} sem resposta dentro de {timeout_segundos}s. Iniciando em modo offline.")
        return False

    def levantar_braco(self) -> None:
        self.conexao.write("SUBIR\n".encode())
        self.conexao.flush()

    def abaixar_braco(self) -> None:
        if self.conexao.is_open:
            self.conexao.write("DESCER\n".encode())
            self.conexao.flush()

    def fechar(self) -> None:
        if self.conexao.is_open:
            self.conexao.close()


class NovaAssistant:
    """
    Classe principal da assistente de voz Nova.

    Gerencia o ciclo de escuta, reconhecimento de voz, interpretação de
    comandos e execução das ações correspondentes (agenda, cálculos,
    reconhecimento facial, integração com IA etc.).
    """

    # Palavra-chave de ativação: toda fala deve começar com "nova"
    WAKE_WORD = "nova"

    # Índice padrão do microfone (ajuste conforme seu hardware)
    DEFAULT_MICROPHONE_INDEX = 2

    # Índice padrão da câmera (ajuste conforme seu hardware)
    DEFAULT_CAMERA_INDEX = 0

    # Label e nome da pessoa principal no modelo de reconhecimento facial
    PRIMARY_FACE_LABEL = 1
    PRIMARY_FACE_NAME = "Guilherme"

    # Limite de confiança para reconhecimento facial (menor = mais restrito)
    PRIMARY_FACE_CONFIDENCE_LIMIT = 4500.0

    # Voz neural do Edge TTS (pt-BR-FranciscaNeural = feminina | pt-BR-AntonioNeural = masculina)
    EDGE_TTS_VOICE = "pt-BR-FranciscaNeural"

    def __init__(self) -> None:
        """Inicializa a assistente: caminhos, reconhecedor de voz e motor de fala."""
        # Diretório base onde ficam agenda.txt e o modelo facial
        self.base_dir = Path(__file__).resolve().parent
        self.agenda_path = self.base_dir / "agenda.txt"
        self.face_model_path = self._resolve_face_model_path()

        # Reconhecedor de voz do Google (via SpeechRecognition)
        self.recognizer = sr.Recognizer()

        # Motor de síntese de voz SAPI5 — usado apenas como fallback
        self.speaker = self._create_windows_speaker()

        # Inicializa o mixer do pygame para reproduzir áudio do Edge TTS
        self.use_edge_tts = self._init_pygame()

        # Flag que indica se a assistente aguarda o nome do evento a cadastrar
        self.pending_agenda_event = False

        # Flag que indica se a assistente aguarda uma pergunta para enviar à IA
        self.pending_ai_question = False

        # Estado de conversa acionado pelo detector experimental de queda.
        self.pending_fall_response = False
        self.fall_response_deadline = 0.0
        self.safety_events: queue.Queue[str] = queue.Queue()
        self.monitor_threads: list[threading.Thread] = []
        self.monitor_stop = threading.Event()
        self.camera_paused = threading.Event()
        self.camera_lock = threading.Lock()

        # Flag que controla o loop principal de escuta
        self.running = True

        self._setup_speech()

    def start_monitors(self) -> None:
        """Inicia a análise contínua da webcam."""
        if os.getenv("NOVA_FALL_MONITOR", "1").strip() != "0":
            thread = threading.Thread(
                target=self._fall_monitor_loop, name="nova-fall-monitor", daemon=True
            )
            thread.start()
            self.monitor_threads.append(thread)

    def stop_monitors(self) -> None:
        """Pede que os monitores em segundo plano parem ao encerrar o programa."""
        self.monitor_stop.set()

    def _fall_monitor_loop(self) -> None:
        """Procura deslocamento brusco e perda sustentada de uma pessoa detectada."""
        camera_index = self.choose_camera_index()
        if camera_index is None:
            print("Monitoramento de queda indisponível: webcam não encontrada.")
            return

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        previous_person_center: Optional[tuple[float, float]] = None
        fall_candidate_at: Optional[float] = None
        missing_person_frames = 0
        fall_latched = False
        camera = None
        show_camera = True
        camera_window_created = False
        camera_window_name = "AlertaVida - Monitoramento"
        print(f"Monitoramento demonstrativo de queda ativo na câmera {camera_index}.")
        try:
            while not self.monitor_stop.is_set():
                if self.camera_paused.is_set():
                    if camera is not None:
                        camera.release()
                        camera = None
                    if camera_window_created:
                        cv2.destroyWindow(camera_window_name)
                        camera_window_created = False
                    time.sleep(0.1)
                    continue
                if camera is None:
                    camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
                    if not camera.isOpened():
                        camera.release()
                        camera = None
                        time.sleep(1)
                        continue
                if not self.camera_lock.acquire(timeout=0.2):
                    continue  # Reconhecimento facial/contagem está usando a webcam.
                try:
                    ok, frame = camera.read()
                finally:
                    self.camera_lock.release()
                if not ok:
                    time.sleep(0.2)
                    continue

                # Heurística demonstrativa: procura deslocamento vertical brusco
                # de uma pessoa detectada, seguido pela perda sustentada da detecção.
                # Um quadro um pouco maior ajuda a localizar pessoas mais
                # afastadas da webcam sem aumentar demais o custo do HOG.
                frame = cv2.resize(frame, (800, 450))
                # O detector HOG é treinado principalmente para pessoas em pé.
                # Uma escala menor e um limiar um pouco mais permissivo ajudam
                # quando o corpo aparece parcialmente ou começa a se abaixar.
                boxes, _weights = hog.detectMultiScale(
                    frame,
                    hitThreshold=-0.3,
                    winStride=(6, 6),
                    padding=(8, 8),
                    scale=1.04,
                )
                now = time.monotonic()
                if len(boxes):
                    x, y, width, height = max(boxes, key=lambda box: box[2] * box[3])
                    center = (x + width / 2, y + height / 2)
                    if previous_person_center is not None:
                        dx = abs(center[0] - previous_person_center[0])
                        dy = center[1] - previous_person_center[1]
                        # Uma descida mais curta já inicia a janela de possível
                        # queda; HOG costuma oscilar alguns pixels entre quadros.
                        if dy >= 25 and dx <= 200:
                            fall_candidate_at = now
                            missing_person_frames = 0
                    previous_person_center = center
                    if fall_candidate_at is not None and now - fall_candidate_at > 3:
                        fall_candidate_at = None
                        missing_person_frames = 0
                else:
                    previous_person_center = None
                    if fall_candidate_at is not None and now - fall_candidate_at <= 3:
                        missing_person_frames += 1
                    else:
                        fall_candidate_at = None
                        missing_person_frames = 0

                if missing_person_frames >= 4 and not fall_latched:
                    self.safety_events.put("fall")
                    fall_latched = True
                    fall_candidate_at = None
                    missing_person_frames = 0
                elif fall_latched and len(boxes):
                    # Rearma após a pessoa voltar a ser detectada por alguns segundos.
                    if previous_person_center is not None and previous_person_center[1] < 200:
                        fall_latched = False

                if show_camera:
                    for x, y, width, height in boxes:
                        cv2.rectangle(
                            frame, (x, y), (x + width, y + height), (0, 220, 0), 2
                        )
                    status = (
                        "POSSIVEL QUEDA DETECTADA"
                        if fall_latched
                        else (
                            "PESSOA DETECTADA | Q fecha a previa"
                            if len(boxes)
                            else "PROCURANDO PESSOA | Q fecha a previa"
                        )
                    )
                    cv2.putText(
                        frame,
                        status,
                        (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.62,
                        (0, 0, 255) if fall_latched else (0, 220, 0),
                        2,
                    )
                    cv2.imshow(camera_window_name, frame)
                    camera_window_created = True
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        show_camera = False
                        cv2.destroyWindow(camera_window_name)
                        camera_window_created = False
                time.sleep(0.15)
        except Exception as error:
            print(f"Erro no monitoramento de queda: {error}")
        finally:
            if camera is not None:
                camera.release()
            if camera_window_created:
                cv2.destroyWindow(camera_window_name)

    def process_safety_events(self) -> None:
        """Trata eventos de sensor/câmera e a resposta pendente sobre uma queda."""
        while True:
            try:
                event = self.safety_events.get_nowait()
            except queue.Empty:
                break
            if event == "fall" and not self.pending_fall_response:
                self.pending_fall_response = True
                self.fall_response_deadline = time.monotonic() + 15
                self.respond("Possível queda detectada. Você está bem? Responda sim ou não.")

        if self.pending_fall_response and time.monotonic() >= self.fall_response_deadline:
            self.pending_fall_response = False
            self.respond("Não recebi uma confirmação de que está tudo bem. Estou acionando ajuda.")

    def handle_fall_answer(self, phrase: str) -> None:
        """Classifica a resposta verbal à pergunta de segurança."""
        answer = self.normalize_text(phrase)
        safe_answers = ("sim", "estou bem", "tudo bem", "to bem", "estou ok", "ok")
        unsafe_answers = ("nao", "ajuda", "machucado", "machucada", "caido", "caida")
        if any(token in answer.split() or token in answer for token in unsafe_answers):
            self.pending_fall_response = False
            self.respond("Entendi. Estou acionando ajuda.")
        elif any(token in answer.split() or token in answer for token in safe_answers):
            self.pending_fall_response = False
            self.respond("Que bom. Vou cancelar o alerta de queda.")
        else:
            self.respond("Não entendi sua resposta. Você está bem? Responda sim ou não.")

    def _setup_speech(self) -> None:
        """Configura velocidade e volume do motor de fala SAPI5 (usado como fallback)."""
        if hasattr(self.speaker, "setProperty"):
            self.speaker.setProperty("rate", 180)
            self.speaker.setProperty("volume", 1)

    @staticmethod
    def _init_pygame() -> bool:
        """
        Inicializa o mixer do pygame para reprodução de áudio do Edge TTS.

        Retorna True se o pygame estiver disponível e iniciado com sucesso,
        False caso contrário (a assistente usará SAPI5 como fallback).
        """
        try:
            import pygame  # noqa: PLC0415
            pygame.mixer.init()
            return True
        except Exception as error:
            print(f"pygame não disponível, usando voz SAPI5: {error}")
            return False

    @staticmethod
    def _create_windows_speaker():
        """
        Cria o motor SAPI5 usado como fallback quando Edge TTS não estiver disponível
        (sem internet ou sem o pacote edge-tts instalado).
        """
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Volume = 100
            speaker.Rate = 0
            return speaker
        except Exception:
            # Fallback: pyttsx3 com SAPI5
            speaker = pyttsx3.init("sapi5")
            speaker.setProperty("rate", 180)
            speaker.setProperty("volume", 1)
            return speaker

    def _resolve_face_model_path(self) -> Path:
        """
        Localiza o arquivo YAML do modelo de reconhecimento facial.

        Verifica os caminhos candidatos e retorna o primeiro que existir.
        Caso nenhum exista, retorna o caminho padrão (erro tratado na chamada).
        """
        candidates = [
            self.base_dir / "ReconhecimentoFacial" / "classificadoreigen.yml",
            self.base_dir.parent / "ReconhecimentoFacial" / "classificadoreigen.yml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]  # Será tratado com mensagem de erro ao usar

    # ──────────────────────────────────────────────
    # Loop principal
    # ──────────────────────────────────────────────

    def run(self) -> None:
        """
        Inicia o loop principal da assistente.

        1. Exibe ajuda inicial e fala saudação.
        2. Seleciona o microfone.
        3. Entra em loop: ouve, normaliza, verifica wake word e despacha comando.
        """
        self.print_startup_help()
        self.speak("Nova pronta. Diga Nova seguido do comando desejado.")

        mic_index = self.choose_microphone_index()
        mic_name = self.get_microphone_name(mic_index)
        print(f"Usando microfone: {mic_name}")

        try:
            source_factory = (
                lambda: sr.Microphone(device_index=mic_index)
                if mic_index is not None
                else sr.Microphone()
            )
            with source_factory() as microphone:
                print("Aguarde, ajustando o microfone.")
                # Calibra o reconhecedor para o ruído ambiente
                self.recognizer.adjust_for_ambient_noise(microphone, duration=1)
                self.start_monitors()

                while self.running:
                    self.process_safety_events()
                    phrase = self.listen_once(
                        microphone,
                        timeout=2 if self.pending_fall_response else 3,
                        phrase_time_limit=5 if self.pending_fall_response else 8,
                    )
                    if phrase is None:
                        continue  # Timeout ou fala não reconhecida — tenta novamente

                    normalized = self.normalize_text(phrase)
                    print(f"Reconhecido: {phrase}")

                    # Verifica comando de encerramento sem precisar da wake word
                    if self.is_exit_command(normalized):
                        self.shutdown()
                        continue

                    if self.pending_fall_response:
                        self.handle_fall_answer(phrase)
                        continue

                    # Se a assistente está aguardando o nome de um evento, captura a fala
                    if self.pending_agenda_event:
                        self.save_agenda_event(phrase)
                        self.pending_agenda_event = False
                        self.speak("Evento cadastrado na agenda.")
                        continue

                    # Se está aguardando uma pergunta para a IA, envia direto sem exigir wake word
                    if self.pending_ai_question:
                        self.pending_ai_question = False
                        self.call_ai_with_prompt(phrase)
                        continue

                    # Ignora falas que não começam com "nova"
                    if not self.has_wake_word(normalized):
                        continue

                    # Remove a wake word e obtém apenas o comando
                    command = self.remove_wake_word(normalized)
                    if not command:
                        self.speak("Sim?")
                        continue

                    self.handle_command(command, phrase)

        except Exception as error:
            print(f"Erro ao abrir o microfone: {error}")
            print("Tentando usar o microfone padrão do sistema.")
            try:
                with sr.Microphone() as microphone:
                    self.recognizer.adjust_for_ambient_noise(microphone, duration=0.5)
                    print("Microfone padrão do sistema OK. Assistente continuando em operação.")
                    self.start_monitors()
                    while self.running:
                        self.process_safety_events()
                        phrase = self.listen_once(
                            microphone,
                            timeout=2 if self.pending_fall_response else 3,
                            phrase_time_limit=5 if self.pending_fall_response else 8,
                        )
                        if phrase is None:
                            continue
                        normalized = self.normalize_text(phrase)
                        if self.is_exit_command(normalized):
                            self.shutdown()
                            continue
                        if self.pending_fall_response:
                            self.handle_fall_answer(phrase)
                            continue
                        if self.pending_agenda_event:
                            self.save_agenda_event(phrase)
                            self.pending_agenda_event = False
                            self.speak("Evento cadastrado na agenda.")
                            continue
                        if self.pending_ai_question:
                            self.pending_ai_question = False
                            self.call_ai_with_prompt(phrase)
                            continue
                        if not self.has_wake_word(normalized):
                            continue
                        command = self.remove_wake_word(normalized)
                        if not command:
                            self.speak("Sim?")
                            continue
                        self.handle_command(command, phrase)
            except Exception as fallback_error:
                print(f"Não foi possível usar nenhum microfone: {fallback_error}")
                self.respond("Microfone indisponível. A assistente foi iniciada em modo sem áudio.")
        finally:
            self.stop_monitors()

    def listen_once(
        self, microphone: sr.Microphone, timeout: int = 6, phrase_time_limit: int = 8
    ) -> Optional[str]:
        """
        Escuta uma única fala e retorna o texto reconhecido.

        Usa o serviço Google Speech Recognition (requer internet).
        Retorna None em caso de silêncio, fala ininteligível ou erro de rede.
        """
        try:
            audio = self.recognizer.listen(
                microphone, timeout=timeout, phrase_time_limit=phrase_time_limit
            )
            return self.recognizer.recognize_google(audio, language="pt-BR")
        except sr.WaitTimeoutError:
            return None  # Silêncio por tempo demais — normal, tenta de novo
        except sr.UnknownValueError:
            print("Não entendi a fala.")
            return None
        except sr.RequestError as error:
            print(f"Erro no serviço de reconhecimento: {error}")
            self.speak("Não consegui acessar o reconhecimento de voz no momento.")
            return None

    # ──────────────────────────────────────────────
    # Roteador de comandos
    # ──────────────────────────────────────────────

    def handle_command(self, command: str, original_phrase: str) -> None:
        """
        Identifica o comando reconhecido e chama a função correspondente.

        O parâmetro `command` já vem sem a wake word e normalizado (sem acentos,
        lowercase). O `original_phrase` é usado apenas quando a query precisa
        preservar maiúsculas/minúsculas (ex: busca no Google).
        """
        # Encerramento da assistente
        if self.is_exit_command(command):
            self.shutdown()
            return

        # ── Agenda ─────────────────────────────────
        if command.startswith("cadastrar evento na agenda") or command.startswith("cadastrar evento"):
            self.respond("Ok, qual evento devo cadastrar?")
            self.pending_agenda_event = True  # Próxima fala será o nome do evento
            return

        if command.startswith("ler agenda"):
            self.read_agenda()
            return

        if command.startswith("limpar agenda"):
            self.clear_agenda()
            return

        # ── Data e hora ────────────────────────────
        if command.startswith("que horas sao") or command.startswith("que horas são"):
            self.tell_time()
            return

        if command.startswith("que dia e hoje") or command.startswith("que dia é hoje"):
            self.tell_date()
            return

        # ── Calculadora ────────────────────────────
        if (
            command.startswith("calcular")
            or command.startswith("quanto e")
            or command.startswith("quanto é")
            or command.startswith("quando e")
            or command.startswith("quando é")
            or command.startswith("qual o resultado de")
        ):
            self.calculate(command)
            return

        # ── Reconhecimento facial ──────────────────
        if command.startswith("reconhecer face"):
            self.recognize_face()
            return

        if command.startswith("quem sou eu"):
            self.identify_me()
            return

        if command.startswith("quantas pessoas") or command.startswith("contar pessoas"):
            self.count_people()
            return

        # ── IA generativa (Ollama) ─────────────────
        # Aceita várias formas de acionar a IA ("ia" é difícil de reconhecer sozinho)
        ai_triggers = (
            "conversar com a ia", "falar com a ia", "perguntar", "pergunta",
            "ia ", "inteligencia artificial",
        )
        if command == "ia" or any(command.startswith(t) for t in ai_triggers):
            self.call_ai(command)
            return

        # ── Comandos extras ────────────────────────
        if command.startswith("pesquisar no google"):
            query = command.replace("pesquisar no google", "", 1).strip()
            self.search_google(query or original_phrase)
            return

        if command.startswith("abrir youtube"):
            query = command.replace("abrir youtube", "", 1).strip()
            self.open_youtube(query or "")
            return

        # Comando não reconhecido — apenas registra no console
        print(f"Comando ignorado: {original_phrase}")

    # ──────────────────────────────────────────────
    # Agenda
    # ──────────────────────────────────────────────

    def read_agenda(self) -> None:
        """
        Lê e fala todos os eventos cadastrados na agenda.txt.

        Cada linha do arquivo corresponde a um evento. Se o arquivo não existir
        ou estiver vazio, informa o usuário.
        """
        if not self.agenda_path.exists():
            self.respond("A agenda ainda está vazia.")
            return

        content = self.agenda_path.read_text(encoding="utf-8").strip()
        if not content:
            self.respond("A agenda está vazia.")
            return

        self.respond("Lendo agenda.")
        print("Agenda:")
        for line in content.splitlines():
            line = line.strip()
            if line:
                self.respond(line)  # Fala cada evento individualmente

    def save_agenda_event(self, event_text: str) -> None:
        """
        Salva um novo evento no final do arquivo agenda.txt.

        Cria o arquivo (e os diretórios necessários) caso não existam.
        Cada evento ocupa uma linha separada.
        """
        self.agenda_path.parent.mkdir(parents=True, exist_ok=True)
        with self.agenda_path.open("a", encoding="utf-8") as file:
            file.write(event_text.strip() + "\n")
        print(f"Evento salvo: {event_text}")

    def clear_agenda(self) -> None:
        """
        Apaga o conteúdo da agenda sem excluir o arquivo.

        O arquivo agenda.txt é mantido no disco, porém seu conteúdo é
        sobrescrito com uma string vazia.
        """
        self.agenda_path.write_text("", encoding="utf-8")
        self.respond("Agenda limpa.")
        print("Agenda limpa.")

    # ──────────────────────────────────────────────
    # Data e hora
    # ──────────────────────────────────────────────

    def tell_time(self) -> None:
        """Fala a hora e os minutos atuais no formato 'Agora são HH horas e MM minutos'."""
        agora = datetime.now()
        texto = agora.strftime("Agora são %H horas e %M minutos.")
        self.respond(texto)

    def tell_date(self) -> None:
        """Fala a data atual em português (ex: 'Hoje é terça-feira, 02 de setembro de 2026')."""
        agora = datetime.now()
        texto = self.format_date_ptbr(agora)
        self.respond(texto)

    @staticmethod
    def format_date_ptbr(moment: datetime) -> str:
        """
        Converte um objeto datetime para uma string de data em português.

        Retorna algo como: 'Hoje é terça-feira, 02 de setembro de 2026.'
        """
        weekdays = [
            "segunda-feira",
            "terça-feira",
            "quarta-feira",
            "quinta-feira",
            "sexta-feira",
            "sábado",
            "domingo",
        ]
        months = [
            "janeiro", "fevereiro", "março", "abril",
            "maio", "junho", "julho", "agosto",
            "setembro", "outubro", "novembro", "dezembro",
        ]
        weekday = weekdays[moment.weekday()]
        month = months[moment.month - 1]
        return f"Hoje é {weekday}, {moment.day:02d} de {month} de {moment.year}."

    # ──────────────────────────────────────────────
    # Calculadora
    # ──────────────────────────────────────────────

    def calculate(self, command: str) -> None:
        """
        Interpreta e calcula uma expressão matemática falada pelo usuário.

        Converte palavras como 'mais', 'menos', 'vezes', 'dividido por' nos
        operadores aritméticos correspondentes antes de avaliar a expressão.
        Usa `safe_eval` para garantir segurança (sem exec/eval inseguro).
        """
        expression = self.extract_calculation_expression(command)
        if not expression:
            self.respond("Diga uma conta para eu calcular.")
            return

        # Normaliza e substitui termos por operadores matemáticos
        normalized = self.normalize_text(expression)
        normalized = normalized.replace("mais", "+")
        normalized = normalized.replace("menos", "-")
        normalized = normalized.replace("vezes", "*")
        normalized = normalized.replace("multiplicado por", "*")
        normalized = normalized.replace("dividido por", "/")
        normalized = re.sub(r"\bx\b", "*", normalized)  # "x" como multiplicação
        normalized = normalized.replace("÷", "/")

        try:
            result = self.safe_eval(normalized)
            texto = f"O resultado é {result}"
            self.respond(texto)
        except (ValueError, SyntaxError, ZeroDivisionError):
            self.respond("Não consegui entender a conta.")

    @staticmethod
    def extract_calculation_expression(command: str) -> str:
        """
        Remove o prefixo do comando de cálculo, retornando apenas a expressão.

        Exemplo: 'calcular 2 mais 3' → '2 mais 3'
        """
        prefixes = (
            "calcular",
            "quanto e",
            "quanto é",
            "quando e",
            "quando é",
            "qual o resultado de",
        )
        for prefix in prefixes:
            if command.startswith(prefix):
                return command.replace(prefix, "", 1).strip()
        return command.strip()

    def safe_eval(self, expression: str) -> float:
        """
        Avalia uma expressão aritmética de forma segura usando a AST do Python.

        Permite apenas nós de operações matemáticas básicas (sem chamadas de
        função, atributos ou imports), prevenindo injeção de código malicioso.

        Operações suportadas: +, -, *, /, **, %, //
        Levanta ValueError se a expressão contiver nós não permitidos.
        """
        # Apenas estes tipos de nó AST são permitidos na expressão
        allowed_nodes = (
            ast.Expression, ast.BinOp, ast.UnaryOp,
            ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.Pow, ast.USub, ast.UAdd,
            ast.Constant, ast.Mod, ast.FloorDiv, ast.Load,
        )

        node = ast.parse(expression, mode="eval")

        # Verifica que todos os nós da árvore são permitidos
        for child in ast.walk(node):
            if not isinstance(child, allowed_nodes):
                raise ValueError("Expressão não permitida")

        def eval_node(current: ast.AST) -> float:
            """Avalia recursivamente um nó da AST e retorna seu valor numérico."""
            if isinstance(current, ast.Expression):
                return eval_node(current.body)
            if isinstance(current, ast.Constant) and isinstance(current.value, (int, float)):
                return float(current.value)
            if isinstance(current, ast.UnaryOp):
                operand = eval_node(current.operand)
                if isinstance(current.op, ast.USub):
                    return -operand
                if isinstance(current.op, ast.UAdd):
                    return operand
            if isinstance(current, ast.BinOp):
                left = eval_node(current.left)
                right = eval_node(current.right)
                # Mapa de tipos de operação para funções lambda
                operations = {
                    ast.Add:      lambda a, b: a + b,
                    ast.Sub:      lambda a, b: a - b,
                    ast.Mult:     lambda a, b: a * b,
                    ast.Div:      lambda a, b: a / b,
                    ast.Pow:      lambda a, b: a ** b,
                    ast.Mod:      lambda a, b: a % b,
                    ast.FloorDiv: lambda a, b: a // b,
                }
                for op_type, operation in operations.items():
                    if isinstance(current.op, op_type):
                        return float(operation(left, right))
            raise ValueError("Expressão inválida")

        return eval_node(node)

    # ──────────────────────────────────────────────
    # Reconhecimento facial
    # ──────────────────────────────────────────────

    def recognize_face(self) -> None:
        """
        Abre a webcam e identifica faces usando o modelo pré-treinado.

        Reconhece Guilherme (label 1).
        Qualquer outra face é classificada como 'Desconhecido'.
        Pressione Q para encerrar a janela.
        """
        self._run_face_recognition(
            labels={
                1: "Guilherme",
            },
            announcement="Abrindo a webcam para reconhecimento facial. Pressione Q para sair.",
            confidence_limit=self.PRIMARY_FACE_CONFIDENCE_LIMIT,
        )

    def identify_me(self) -> None:
        """
        Abre a webcam e tenta identificar se a pessoa é o usuário principal.

        Usa o limite de confiança `PRIMARY_FACE_CONFIDENCE_LIMIT` para evitar
        falsos positivos: se a confiança for alta demais (menos certo), classifica
        como 'Desconhecido'. Pressione Q para encerrar.
        """
        self._run_face_recognition(
            labels={
                self.PRIMARY_FACE_LABEL: self.PRIMARY_FACE_NAME,
            },
            announcement="Abrindo a webcam para identificar você. Pressione Q para sair.",
            confidence_limit=self.PRIMARY_FACE_CONFIDENCE_LIMIT,
        )

    def _run_face_recognition(
        self,
        labels: dict[int, str],
        announcement: str,
        confidence_limit: Optional[float] = None,
    ) -> None:
        """
        Executa o loop de reconhecimento facial com o modelo EigenFace treinado.

        Parâmetros
        ----------
        labels : dict[int, str]
            Mapeamento de label numérico para nome da pessoa.
        announcement : str
            Texto que a assistente fala antes de abrir a câmera.
        confidence_limit : float | None
            Se definido, faces com confiança acima desse valor são tratadas como
            'Desconhecido' (EigenFace: menor confiança = maior certeza).
        """
        # Verifica pré-requisitos: modelo e módulo opencv-contrib
        if not self.face_model_path.exists():
            self.respond("O modelo de reconhecimento facial não foi encontrado.")
            return

        if not hasattr(cv2, "face"):
            self.respond("Seu OpenCV não possui o módulo de reconhecimento facial.")
            return

        # Carrega o detector Haar e o reconhecedor EigenFace treinado
        detector_face = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        recognizer = cv2.face.EigenFaceRecognizer_create()
        try:
            recognizer.read(str(self.face_model_path))
        except cv2.error as error:
            print(f"Não consegui carregar o modelo facial: {error}")
            self.respond("Não consegui carregar o modelo de reconhecimento facial.")
            return

        camera_index = self.choose_camera_index()
        if camera_index is None:
            self.respond("Não encontrei nenhuma câmera disponível neste computador.")
            return

        print(f"Usando câmera: {camera_index}")
        self.camera_paused.set()
        time.sleep(0.5)  # Dá tempo ao monitor contínuo para liberar a webcam.
        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not camera.isOpened():
            camera.release()
            self.camera_paused.clear()
            self.respond("Não consegui abrir a webcam.")
            return

        try:
            self.respond(announcement)
            while True:
                status, frame = camera.read()
                if not status:
                    break

                # Converte para escala de cinza (necessário para detecção facial)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = detector_face.detectMultiScale(gray, scaleFactor=1.5, minSize=(30, 30))

                for x, y, width, height in faces:
                    # Redimensiona a face para o tamanho esperado pelo modelo (220x220)
                    face_image = cv2.resize(gray[y:y + height, x:x + width], (220, 220))
                    label, confidence = recognizer.predict(face_image)
                    name = labels.get(label, "Desconhecido")

                    # Aplica limite de confiança se fornecido
                    if confidence_limit is not None and (label not in labels or confidence > confidence_limit):
                        name = "Desconhecido"

                    # Desenha retângulo e nome na imagem
                    cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 0, 255), 2)
                    cv2.putText(
                        frame, f"{name} ({confidence:.0f})",
                        (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
                    )
                    print(f"Face detectada: {name} - confiança {confidence:.2f}")

                cv2.imshow("Nova - Reconhecimento Facial", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            # Garante liberação da câmera mesmo em caso de erro
            camera.release()
            cv2.destroyAllWindows()
            self.camera_paused.clear()

    def count_people(self) -> None:
        """
        Conta quantas pessoas aparecem na webcam usando detecção Haar Cascade.

        Não realiza identificação — apenas detecta rostos e conta.
        Ao pressionar Q, fala o número de pessoas detectadas no último frame.
        """
        if not hasattr(cv2, "face"):
            self.respond("Seu OpenCV não possui o módulo necessário para a detecção facial.")
            return

        detector_face = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        camera_index = self.choose_camera_index()
        if camera_index is None:
            self.respond("Não encontrei nenhuma câmera disponível neste computador.")
            return

        print(f"Usando câmera: {camera_index}")
        self.camera_paused.set()
        time.sleep(0.5)
        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not camera.isOpened():
            camera.release()
            self.camera_paused.clear()
            self.respond("Não consegui abrir a webcam.")
            return

        last_count = 0  # Armazena a contagem do último frame processado

        try:
            self.respond("Abrindo a webcam para contar pessoas. Pressione Q para sair.")
            while True:
                status, frame = camera.read()
                if not status:
                    break

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = detector_face.detectMultiScale(gray, scaleFactor=1.5, minSize=(30, 30))
                last_count = len(faces)

                # Desenha retângulo azul em cada rosto detectado
                for x, y, width, height in faces:
                    cv2.rectangle(frame, (x, y), (x + width, y + height), (255, 0, 0), 2)

                cv2.putText(
                    frame, f"Pessoas detectadas: {last_count}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2,
                )
                print(f"Pessoas detectadas no frame: {last_count}")
                cv2.imshow("Nova - Contagem de Pessoas", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            camera.release()
            cv2.destroyAllWindows()
            self.camera_paused.clear()

        # Anuncia o resultado após fechar a janela
        if last_count == 0:
            self.respond("Não detectei nenhuma pessoa na câmera.")
        elif last_count == 1:
            self.respond("Detectei uma pessoa na câmera.")
        else:
            self.respond(f"Detectei {last_count} pessoas na câmera.")

    # ──────────────────────────────────────────────
    # IA generativa (Ollama / LLaMA)
    # ──────────────────────────────────────────────

    def call_ai(self, command: str) -> None:
        """
        Envia uma pergunta para o modelo de linguagem local (Ollama) e fala a resposta.

        Se o prompt vier junto ao comando (ex: 'perguntar qual a capital'), envia direto.
        Se o comando vier vazio (só 'nova ia'), entra em modo pendente e aguarda a
        próxima fala do usuário como pergunta — sem exigir a wake word novamente.
        """
        # Remove todos os prefixos possíveis, mantendo apenas a pergunta
        prompt = command
        for prefix in (
            "conversar com a ia", "falar com a ia",
            "inteligencia artificial", "perguntar", "pergunta", "ia",
        ):
            if prompt.startswith(prefix):
                prompt = prompt.replace(prefix, "", 1).strip()
                break

        if not prompt:
            # Nenhum prompt junto ao comando — aguarda a próxima fala
            self.respond("Pode perguntar.")
            self.pending_ai_question = True
            return

        self.call_ai_with_prompt(prompt)

    def call_ai_with_prompt(self, prompt: str) -> None:
        """
        Envia o prompt diretamente ao Ollama e fala a resposta.

        Separado de call_ai para ser reutilizado tanto pelo fluxo normal
        quanto pelo fluxo de estado pendente (pending_ai_question).
        """
        answer = self.ask_ollama(prompt)
        if not answer:
            self.respond("Não consegui responder pela IA agora.")
            return

        self.respond(f"IA: {answer}")

    def ask_ollama(self, prompt: str) -> Optional[str]:
        """
        Realiza uma requisição HTTP à API do Ollama e retorna a resposta do modelo.

        Usa o modelo llama3.1:8b rodando localmente. A resposta é solicitada
        em português e de forma objetiva. Retorna None em caso de falha.
        """
        model = "llama3.1:8b"
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": f"Responda em português, de forma objetiva: {prompt}",
                    "stream": False,  # Recebe a resposta completa de uma vez
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip() or None
        except Exception as error:
            print(f"Erro ao consultar a IA local: {error}")
            return None

    # ──────────────────────────────────────────────
    # Comandos extras
    # ──────────────────────────────────────────────

    def search_google(self, query: str) -> None:
        """
        Abre o navegador padrão com uma busca no Google.

        A query é codificada em URL para suportar caracteres especiais e espaços.
        """
        if not query:
            self.respond("Diga o que devo pesquisar no Google.")
            return

        url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        webbrowser.open(url)
        self.respond(f"Pesquisando no Google por {query}.")

    def open_youtube(self, query: str) -> None:
        """
        Abre o YouTube no navegador padrão.

        Se uma query for fornecida, abre diretamente os resultados de busca.
        Caso contrário, abre a página inicial do YouTube.
        """
        if query:
            url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
        else:
            url = "https://www.youtube.com"
        webbrowser.open(url)
        self.respond("Abrindo o YouTube.")

    # ──────────────────────────────────────────────
    # Síntese de voz
    # ──────────────────────────────────────────────

    def speak(self, text: str) -> None:
        """
        Fala o texto usando Edge TTS neural (voz natural) com fallback para SAPI5.

        Prioridade:
        1. Edge TTS (pt-BR-FranciscaNeural) — requer edge-tts, pygame e internet.
        2. SAPI5 via win32com — voz robótica, mas funciona offline.
        3. pyttsx3 — último recurso.
        """
        if self.use_edge_tts:
            try:
                self._speak_edge_tts(text)
                return
            except Exception as error:
                # Sem internet ou erro pontual — cai no SAPI5
                print(f"Edge TTS falhou ({error}), usando SAPI5...")

        self._speak_fallback(text)

    def _speak_edge_tts(self, text: str) -> None:
        """
        Sintetiza o texto com Edge TTS e reproduz via pygame.

        Gera um arquivo MP3 temporário, reproduz e remove em seguida.
        Bloqueia até o áudio terminar (comportamento síncrono).
        """
        asyncio.run(self._edge_tts_async(text))

    async def _edge_tts_async(self, text: str) -> None:
        """
        Corrotina que gera o áudio via Edge TTS e o reproduz com pygame.

        Usa um arquivo temporário para evitar conflitos entre chamadas.
        O arquivo é removido automaticamente após a reprodução.
        """
        import edge_tts  # noqa: PLC0415
        import pygame    # noqa: PLC0415

        # Gera o áudio em um arquivo temporário
        tmp_path = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(text, voice=self.EDGE_TTS_VOICE)
            await communicate.save(tmp_path)

            # Reproduz o MP3 e aguarda o fim
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.05)
        finally:
            pygame.mixer.music.stop()
            try:
                os.unlink(tmp_path)  # Remove o arquivo temporário
            except OSError:
                pass

    def _speak_fallback(self, text: str) -> None:
        """
        Reproduz o texto usando o motor SAPI5 (fallback quando Edge TTS não estiver disponível).

        Suporta win32com e pyttsx3. Em último caso, imprime no console.
        """
        try:
            if hasattr(self.speaker, "Speak"):
                # Motor SAPI5 via win32com
                self.speaker.Speak(text)
            elif hasattr(self.speaker, "say"):
                # Motor pyttsx3
                self.speaker.say(text)
                self.speaker.runAndWait()
            else:
                self.speaker.speak(text)
        except Exception as error:
            print(f"Erro ao falar: {error}")
            print(text)

    def respond(self, text: str) -> None:
        """Imprime o texto no console e o fala em voz alta."""
        print(text)
        self.speak(text)

    def shutdown(self) -> None:
        """Anuncia o encerramento e para o loop principal da assistente."""
        self.respond("Tchau. Encerrando a assistente.")
        self.running = False
        self.stop_monitors()

    # ──────────────────────────────────────────────
    # Utilitários
    # ──────────────────────────────────────────────

    def print_startup_help(self) -> None:
        """Exibe no console os comandos disponíveis ao iniciar a assistente."""
        print("=" * 60)
        print("Nova Assistente")
        print("Comandos exemplos:")
        print("- Nova cadastrar evento na agenda")
        print("- Nova ler agenda")
        print("- Nova limpar agenda")
        print("- Nova que horas são")
        print("- Nova que dia é hoje")
        print("- Nova calcular 2 + 2")
        print("- Nova reconhecer face")
        print("- Nova quem sou eu")
        print("- Nova quantas pessoas tem")
        print("- Nova ia [pergunta]")
        print("- Nova pesquisar no google [termo]")
        print("- Nova abrir youtube [vídeo]")
        print("- Nova tchau")
        print("Ctrl+C encerra o programa.")
        print("=" * 60)

    @staticmethod
    def _is_valid_microphone_name(name: str) -> bool:
        """Descarta mapeamentos virtuais do Windows e saídas do sistema."""
        lowered = name.lower()
        blocked_terms = (
            "sound mapper",
            "primary sound capture driver",
            "primary sound driver",
            "headphone",
            "speaker",
            "output",
            "stereo mix",
            "loopback",
            "virtual",
            "monitor",
            "audio renderer",
        )
        if any(term in lowered for term in blocked_terms):
            return False
        return ("microphone" in lowered) or ("mic" in lowered) or ("frontmic" in lowered)

    def choose_microphone_index(self) -> Optional[int]:
        """
        Determina o índice do microfone a ser usado.

        Prioridade:
        1. Variável de ambiente NOVA_MICROPHONE_INDEX.
        2. Primeiro dispositivo real de entrada que realmente abre corretamente.
        3. None (usa o microfone padrão do sistema).
        """
        raw_value = os.getenv("NOVA_MICROPHONE_INDEX", "").strip()
        if raw_value:
            try:
                return int(raw_value)
            except ValueError:
                print(f"NOVA_MICROPHONE_INDEX inválido: {raw_value}")

        try:
            names = sr.Microphone.list_microphone_names()
        except Exception as error:
            print(f"Não consegui listar os microfones: {error}")
            return None

        if not names:
            print("Nenhum microfone encontrado. Vou usar o padrão do sistema.")
            return None

        valid_indices = [
            index for index, name in enumerate(names)
            if self._is_valid_microphone_name(name)
        ]
        for index in valid_indices:
            try:
                with sr.Microphone(device_index=index):
                    print(f"Microfone selecionado: [{index}] {names[index]}")
                    return index
            except Exception as error:
                print(f"Microfone [{index}] {names[index]} falhou ao abrir: {error}")

        print("Nenhum microfone de entrada válido foi encontrado. Vou usar o padrão do sistema.")
        return None

    def choose_camera_index(self) -> Optional[int]:
        """
        Determina o índice da câmera a ser usada.

        Prioridade:
        1. Variável de ambiente NOVA_CAMERA_INDEX.
        2. DEFAULT_CAMERA_INDEX e outros índices comuns (0 a 5).
        3. None se nenhuma câmera estiver disponível.
        """
        # Permite override via variável de ambiente
        raw_value = os.getenv("NOVA_CAMERA_INDEX", "").strip()
        if raw_value:
            try:
                camera_index = int(raw_value)
            except ValueError:
                print(f"NOVA_CAMERA_INDEX inválido: {raw_value}")
            else:
                if self.is_camera_available(camera_index):
                    return camera_index
                print(f"NOVA_CAMERA_INDEX definido, mas a câmera {camera_index} não abriu.")

        # Testa índices preferidos em ordem até encontrar uma câmera disponível
        preferred_indices = list(
            dict.fromkeys([self.DEFAULT_CAMERA_INDEX, 0, 1, 2, 3, 4, 5])
        )
        for camera_index in preferred_indices:
            if self.is_camera_available(camera_index):
                return camera_index

        return None

    @staticmethod
    def is_camera_available(camera_index: int) -> bool:
        """Verifica se a câmera abre e realmente entrega um frame no Windows."""
        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        try:
            if not camera.isOpened():
                return False
            ok, _frame = camera.read()
            return ok
        finally:
            camera.release()

    @staticmethod
    def is_exit_command(command: str) -> bool:
        """Retorna True se o comando reconhecido for um comando de encerramento."""
        return command in {"tchau", "sair", "encerrar", "fechar", "parar"}

    def get_microphone_name(self, mic_index: Optional[int]) -> str:
        """Retorna o nome legível do microfone com base no índice, ou 'microfone padrão'."""
        try:
            names = sr.Microphone.list_microphone_names()
            if mic_index is None:
                return names[0] if names else "microfone padrão"
            if 0 <= mic_index < len(names):
                return names[mic_index]
        except Exception:
            pass
        return "microfone padrão"

    def has_wake_word(self, normalized_text: str) -> bool:
        """
        Verifica se o texto normalizado começa com a wake word 'nova'.

        Aceita tanto 'nova [comando]' quanto apenas 'nova' (sem comando).
        """
        return normalized_text.startswith(self.WAKE_WORD + " ") or normalized_text == self.WAKE_WORD

    def remove_wake_word(self, normalized_text: str) -> str:
        """Remove a wake word do início do texto e retorna apenas o comando."""
        if normalized_text == self.WAKE_WORD:
            return ""
        return normalized_text[len(self.WAKE_WORD):].strip()

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normaliza um texto para comparação de comandos.

        Converte para minúsculas, remove acentos (NFD → ASCII), colapsa
        espaços múltiplos e remove caracteres especiais não matemáticos.
        Isso permite reconhecer 'que horas são' e 'que horas sao' como iguais.
        """
        # Remove acentos via decomposição Unicode e re-codificação em ASCII
        normalized = unicodedata.normalize("NFD", text.lower())
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        # Colapsa múltiplos espaços em um único
        normalized = re.sub(r"\s+", " ", normalized)
        # Mantém apenas letras, dígitos e operadores matemáticos básicos
        normalized = re.sub(r"[^a-z0-9+\-*/().,\s]", "", normalized)
        return normalized.strip()


# ──────────────────────────────────────────────────────────────
# Ponto de entrada
# ──────────────────────────────────────────────────────────────

def encontrar_porta_arduino(porta_preferida: str = "") -> Optional[str]:
    """Tenta localizar uma porta serial do Arduino; se não encontrar, retorna None."""
    portas = []
    if porta_preferida.strip():
        portas.append(porta_preferida.strip())
    portas.extend(porta.device for porta in list_ports.comports())
    portas.extend(["COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "COM10", "COM11", "COM12"])

    visitadas: set[str] = set()
    for porta in portas:
        if not porta or porta in visitadas:
            continue
        visitadas.add(porta)
        try:
            with serial.Serial(porta, 9600, timeout=0.2):
                return porta
        except (serial.SerialException, OSError):
            continue
    return None


def main() -> None:
    """Inicia a assistente com ou sem Arduino conectado."""
    porta_arduino = os.getenv("NOVA_ARDUINO_PORT", "").strip()
    porta_arduino = encontrar_porta_arduino(porta_arduino) or porta_arduino or None
    arduino: Optional[ControleArduino] = None

    try:
        if porta_arduino:
            arduino = ControleArduino(porta_arduino)
            if arduino.esperar_presenca(timeout_segundos=10.0):
                arduino.levantar_braco()
            else:
                print("Arduino indisponível ou sem resposta. Iniciando em modo offline sem hardware.")
                arduino = None
        else:
            print("Arduino não encontrado. Iniciando em modo offline sem hardware conectado.")

        nova = NovaAssistant()
        nova.run()
    except serial.SerialException as erro:
        print(f"Não consegui conectar ao Arduino na porta {porta_arduino}: {erro}")
        print("Confira o cabo USB e configure NOVA_ARDUINO_PORT com a porta correta.")
        nova = NovaAssistant()
        nova.run()
    except KeyboardInterrupt:
        print("Inicialização interrompida pelo usuário.")
    finally:
        if arduino is not None:
            try:
                arduino.abaixar_braco()
            finally:
                arduino.fechar()


if __name__ == "__main__":
    main()
