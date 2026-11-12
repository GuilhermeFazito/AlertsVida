#include <Servo.h>

// Pinos do sensor, servo e LEDs de alerta.
const byte pinoPir = 2;
const byte pinoServo = 9;
const byte pinoLed1 = 6;
const byte pinoLed2 = 7;
const int bracoBaixo = 0;
const int bracoEmUso = 80;
const int bracoAlerta = 150;

Servo braco;
bool movimentoAvisado = false;
bool alertaQuedaAtivo = false;
unsigned long ultimoPisca = 0;
bool ledAtual = false;

void moverBraco(int angulo)
{
  braco.write(angulo);
  delay(120);
}

void desligarAlertaQueda()
{
  alertaQuedaAtivo = false;
  digitalWrite(pinoLed1, LOW);
  digitalWrite(pinoLed2, LOW);
  moverBraco(bracoBaixo);
}

void lerComando()
{
  if (!Serial.available())
  {
    return;
  }

  String comando = Serial.readStringUntil('\n');
  comando.trim();

  if (comando == "INICIAR" || comando == "SUBIR")
  {
    moverBraco(30);
    moverBraco(bracoEmUso);
    moverBraco(120);
    moverBraco(bracoEmUso);
  }
  else if (comando == "AJUDA" || comando == "ALERTA_QUEDA")
  {
    alertaQuedaAtivo = true;
    ultimoPisca = millis();
    ledAtual = false;
    digitalWrite(pinoLed1, LOW);
    digitalWrite(pinoLed2, LOW);
    moverBraco(bracoAlerta);
    delay(120);
    moverBraco(100);
    delay(120);
    moverBraco(bracoAlerta);
  }
  else if (comando == "RESETAR" || comando == "DESCER" || comando == "DESLIGAR_ALERTA")
  {
    desligarAlertaQueda();
  }
}

void setup()
{
  pinMode(pinoPir, INPUT);
  pinMode(pinoLed1, OUTPUT);
  pinMode(pinoLed2, OUTPUT);
  desligarAlertaQueda();

  braco.attach(pinoServo);
  braco.write(bracoBaixo);

  Serial.begin(9600);
  Serial.setTimeout(100);
  Serial.println("PRONTO");
}

void loop()
{
  lerComando();

  if (alertaQuedaAtivo && millis() - ultimoPisca >= 250)
  {
    ultimoPisca = millis();
    ledAtual = !ledAtual;
    digitalWrite(pinoLed1, ledAtual ? HIGH : LOW);
    digitalWrite(pinoLed2, ledAtual ? LOW : HIGH);
  }

  const bool detectouMovimento = digitalRead(pinoPir) == HIGH;
  if (detectouMovimento && !movimentoAvisado)
  {
    Serial.println("MOVIMENTO");
    movimentoAvisado = true;
  }
  else if (!detectouMovimento)
  {
    movimentoAvisado = false;
  }

  delay(20);
}
