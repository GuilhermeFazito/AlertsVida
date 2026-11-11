# Nova - Assistente de Voz 

Assistente de voz em português desenvolvida em Python, com reconhecimento facial, integração com IA generativa local e suporte a múltiplos comandos de voz.

---

## Requisitos do Sistema

- **Python** 3.10 ou superior
- **Windows** (usa SAPI5 para síntese de voz)
- **Microfone** funcional
- **Webcam** (para comandos de reconhecimento facial)
- **Conexão com internet** (para reconhecimento de voz via Google e buscas)
- **Ollama** instalado e rodando localmente (para o comando de IA)

---

## Dependências Python

Instale todas as dependências com:

```bash
pip install -r requirements.txt
```

| Pacote | Uso |
|---|---|
| `SpeechRecognition` | Reconhecimento de voz via Google |
| `PyAudio` | Captura de áudio do microfone |
| `pyttsx3` | Síntese de voz (fallback) |
| `requests` | Integração com Ollama e buscas web |
| `opencv-contrib-python` | Detecção e reconhecimento facial (inclui módulo `face`) |
| `pywin32` | Síntese de voz nativa SAPI5 (Windows) |
| `pyserial` | Comunicação entre a NOVA e o Arduino Uno |

> ⚠️ **Atenção**: instale `opencv-contrib-python` e **não** `opencv-python`. Apenas a versão `contrib` inclui o módulo `cv2.face` necessário para o reconhecimento facial.

---

## Instalação do Ollama (IA generativa local)

O comando `Nova ia [pergunta]` requer o Ollama rodando localmente com o modelo LLaMA 3.1.

1. Baixe e instale o Ollama em: https://ollama.com/download
2. Após instalar, baixe o modelo:

```bash
ollama pull llama3.1:8b
```

3. O Ollama deve estar rodando antes de iniciar a assistente. Ele fica em segundo plano automaticamente após a instalação.

---

## Modelo de Reconhecimento Facial

O arquivo de modelo treinado deve estar em:

```
ReconhecimentoFacial/classificadoreigen.yml
```

Este modelo foi treinado com o algoritmo **EigenFace** do OpenCV. As pessoas cadastradas no modelo são:

- **Label 1** → Guilherme
- Outras faces → Desconhecido

---

##  Como executar

```bash
python main.py
```

### Configuração de microfone e câmera (opcional)

Se o microfone ou câmera padrão não for detectado corretamente, defina a variável de ambiente antes de executar:

```bash
# Windows (PowerShell)
$env:NOVA_MICROPHONE_INDEX = "1"
$env:NOVA_CAMERA_INDEX = "0"
python main.py
```

---

## Comandos de Voz

> **Importante**: todo comando deve começar com a palavra **"Nova"**.  
> Exemplo: diga `"Nova que horas são"` — não apenas `"que horas são"`.

### Comandos obrigatórios

| Comando de voz | Ação |
|---|---|
| `Nova` | Ativa a assistente e aguarda comando |
| `Nova cadastrar evento na agenda` | Pergunta o nome do evento e salva em `agenda.txt` |
| `Nova ler agenda` | Lê todos os eventos cadastrados em voz alta |
| `Nova limpar agenda` | Apaga os eventos sem excluir o arquivo |
| `Nova que horas são` | Fala a hora atual |
| `Nova que dia é hoje` | Fala o dia da semana, data e mês |
| `Nova calcular [expressão]` | Calcula e fala o resultado (ex: `Nova calcular 10 mais 5`) |
| `Nova reconhecer face` | Abre a webcam e identifica as pessoas cadastradas |
| `Nova quem sou eu` | Abre a webcam e tenta identificar o usuário principal |
| `Nova perguntar` | Envia a pergunta para o LLaMA local e fala a resposta |

### Comandos extras

| Comando de voz | Ação |
|---|---|
| `Nova pesquisar no google [termo]` | Abre o Google com a busca no navegador |
| `Nova abrir youtube [vídeo]` | Abre o YouTube (com ou sem busca) |
| `Nova quantas pessoas tem` | Conta pessoas visíveis na webcam |

## Monitoramento experimental de queda pela webcam

O monitoramento de queda pela webcam inicia junto com a assistente. A detecção atual é uma heurística demonstrativa baseada no detector HOG do OpenCV: procura um deslocamento vertical brusco de uma pessoa seguido pela perda sustentada da detecção. Pode não reconhecer quedas reais ou gerar falsos alertas, então não deve ser usada como dispositivo de segurança. A Nova pergunta se a pessoa está bem e aguarda até 15 segundos. Uma resposta afirmativa cancela o alerta; uma resposta negativa ou a falta de confirmação faz a Nova dizer que está acionando ajuda.

Execute a assistente com a webcam do computador (troque o índice caso necessário):

```powershell
$env:NOVA_CAMERA_INDEX = "0"
python main.py
```

Essa fala de acionamento é apenas uma simulação: o projeto não chama serviços de emergência nem avisa uma central. Uma integração real exige um canal autorizado e validação humana. Para desligar o monitoramento de queda, defina `$env:NOVA_FALL_MONITOR = "0"` antes de iniciar.

Para iniciar a NOVA pelo sensor, carregue no Arduino Uno o sketch `arduino/AlertaVidaMakerLab/AlertaVidaMakerLab.ino`. O PIR usa o pino **D2** e o sinal do servo usa o pino **D9**. Com o Arduino conectado por USB, execute `python main.py`: o programa fica aguardando o PIR; quando detectar movimento, levanta o servo e inicia a assistente. Ao encerrar a NOVA, o servo volta à posição inicial.

Se o Arduino estiver em outra porta serial, configure-a no PowerShell antes de iniciar (exemplo):

```powershell
$env:NOVA_ARDUINO_PORT = "COM4"
python main.py
```

O padrão é `COM3`. Para um servo que consome mais corrente, use alimentação externa adequada e una o GND da alimentação ao GND do Arduino.

### Encerrar

| Comando | Efeito |
|---|---|
| `Nova tchau` / `Nova sair` / `Nova encerrar` | Encerra a assistente |

---

## Estrutura do Projeto

```
NOVA/
├── main.py                          # Código principal da assistente
├── agenda.txt                       # Arquivo de eventos da agenda
├── requirements.txt                 # Dependências Python
├── README.md                        # Esta documentação
├── arduino/AlertaVidaMakerLab/
│   └── AlertaVidaMakerLab.ino       # PIR e controle do servo
└── ReconhecimentoFacial/
    └── classificadoreigen.yml       # Modelo EigenFace pré-treinado
```

---

## Arquitetura do Código

O projeto é orientado a objetos com uma única classe principal:

- **`NovaAssistant`** — gerencia todo o ciclo de vida da assistente:
  - Loop principal de escuta (`run`, `listen_once`)
  - Roteamento de comandos (`handle_command`)
  - Funções de domínio separadas por responsabilidade (agenda, cálculo, facial, IA, web)
  - Utilitários de normalização de texto e seleção de hardware

---

## Grupo

Projeto desenvolvido por:

Guilherme Doretto Sobreiro - RM:996764

Guilherme Fazito Zioli - RM:550539
