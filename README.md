# Link do video no youtube
https://youtu.be/0aEvn4eHvFc


# AlertaVida

**Monitoramento inteligente de acidentes de trânsito com apoio de inteligência artificial.**

O AlertaVida é uma solução tecnológica que propõe utilizar visão computacional e análise de dados para identificar possíveis acidentes de trânsito em sistemas de câmeras urbanas, gerar alertas e encaminhá-los às equipes responsáveis pela verificação e eventual acionamento dos serviços de emergência.

A proposta é desenvolver uma solução que possa ser integrada à infraestrutura de monitoramento de diferentes municípios, contribuindo para uma identificação mais rápida de ocorrências e um melhor encaminhamento de possíveis vítimas.

> Projeto desenvolvido para a Global Solution 2026.2 da FIAP.

## 2. Integrantes

- Guilherme Doretto Sobreiro — RM 99674
- Guilherme Fazito Ziolli Sordili — RM 550539

## O problema

Acidentes de trânsito podem passar despercebidos ou demorar a ser identificados e encaminhados às equipes responsáveis. Esse intervalo pode comprometer a agilidade na avaliação da ocorrência e no atendimento às vítimas.

O AlertaVida busca contribuir para esse cenário utilizando tecnologia para auxiliar na identificação e no encaminhamento de possíveis acidentes.

## Nossa solução

A proposta é aproveitar sistemas de câmeras já existentes nas cidades para identificar possíveis acidentes automaticamente.

O funcionamento planejado segue este fluxo:

1. **Monitoramento:** utilização de imagens provenientes de sistemas de câmeras urbanas.
2. **Identificação:** processamento das imagens por um modelo de visão computacional treinado para detectar acidentes.
3. **Geração de alerta:** registro da possível ocorrência, com informações relevantes para sua identificação.
4. **Encaminhamento:** envio do alerta para uma central ou setor responsável.
5. **Verificação humana:** análise da ocorrência pelos profissionais responsáveis.
6. **Atendimento:** caso necessário, acionamento dos serviços de emergência, como o SAMU.

A inteligência artificial atua como ferramenta de identificação e apoio. A confirmação da ocorrência e a decisão sobre o atendimento permanecem sob responsabilidade humana.

## Ficha do produto

| Campo | Descrição |
|---|---|
| **Nome do produto** | AlertaVida |
| **Cidadão e território** | Pessoas envolvidas em acidentes de trânsito em áreas urbanas, com aplicação prevista para centrais de monitoramento municipais. |
| **Problema, em uma frase** | Possíveis acidentes podem demorar para ser identificados, avaliados e encaminhados às equipes responsáveis. |
| **Proposta de valor** | Transformar sinais capturados por câmeras em alertas contextualizados, com triagem assistida por IA, referências de apoio e dados territoriais para orientar a validação humana. |
| **Arquitetura: componentes** | Câmeras e vídeos de ocorrências → modelo de visão computacional → API FastAPI do MVP → painel React/Vite → módulo GenAI com recuperação de fontes (RAG), geração e validação de JSON → Databricks SQL Warehouse, mapa, indicadores e central de triagem. |
| **Fontes de dados** | Vídeos de acidentes usados no desenvolvimento, eventos e indicadores armazenados no Databricks SQL Warehouse e base documental institucional em `base/trechos.jsonl`/`base/fontes.csv`, incluindo SAMU, legislação de trânsito, PRF e orientações de emergência. |
| **Modelos de IA utilizados** | YOLO11n personalizado para detecção de acidentes; Qwen/Qwen2.5-1.5B-Instruct para geração local; `intfloat/multilingual-e5-small` para busca semântica; adaptador LoRA opcional para a configuração RAG + LoRA. |
| **URL do MVP e repositório** | MVP local: http://localhost:5173/ · GenAI local: http://localhost:8001/ · Repositório: https://github.com/guidxs/AlertaVida |
| **Indicadores de impacto** | Quantidade de ocorrências identificadas, precisão e recall das detecções, tempo entre identificação e encaminhamento, tempo de triagem, taxa de JSON válido, citação correta das fontes e taxa de recusa quando faltam evidências. |
| **ODS conectados** | **ODS 3 — Saúde e Bem-Estar:** apoia a identificação e o encaminhamento mais rápidos de possíveis acidentes.<br>**ODS 9 — Indústria, Inovação e Infraestrutura:** aplica IA, dados e infraestrutura digital a um desafio de segurança viária.<br>**ODS 10 — Redução das Desigualdades:** busca apoiar o acesso mais equitativo à ajuda, sem depender da capacidade financeira da pessoa. |



## Nova - Assistente de Voz 

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

## Componentes utilizados

| Componente | Quantidade | Função no projeto |
|---|---:|---|
| Arduino Uno | 1 | Controla os componentes eletrônicos e executa o código. |
| Sensor PIR | 1 | Detecta a presença ou o movimento de uma pessoa. |
| LEDs | 2 | Indicam visualmente o estado do sistema. |
| Servomotor | 1 | Movimenta o braço do robô. |


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
