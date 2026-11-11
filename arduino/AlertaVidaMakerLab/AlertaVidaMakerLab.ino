#include <Servo.h>

// Pinos do sensor e do servo.
const byte pinoPir = 2;
const byte pinoServo = 9;
const int bracoBaixo = 0;
const int bracoAlto = 90;

Servo braco;
bool movimentoAvisado = false;

void lerComando() {
  if (!Serial.available()) {
    return;
  }

  String comando = Serial.readStringUntil('\n');
  comando.trim();

  if (comando == "SUBIR") {
    braco.write(bracoAlto);
  } else if (comando == "DESCER") {
    braco.write(bracoBaixo);
  }
}

void setup() {
  pinMode(pinoPir, INPUT);
  braco.attach(pinoServo);
  braco.write(bracoBaixo);

  Serial.begin(9600);
  Serial.setTimeout(100);
  Serial.println("PRONTO");
}

void loop() {
  lerComando();

  const bool detectouMovimento = digitalRead(pinoPir) == HIGH;
  if (detectouMovimento && !movimentoAvisado) {
    Serial.println("MOVIMENTO");
    movimentoAvisado = true;
  } else if (!detectouMovimento) {
    movimentoAvisado = false;
  }

  delay(20);
}
