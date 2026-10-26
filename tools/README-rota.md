A rota é executada com o Python de `fc26-switch/venv`, que tem Pillow, e o
`tesseract` local já instalado. Não usa serviços externos para ler imagens.

A fonte fica neste ramo, em `rev/nxport/tools/rota_robusta.py`. No diretório
compartilhado, `fc26-switch/tools/rota_robusta.py` aponta para essa fonte.
O programa encontra `fc26-switch/work` pelos diretórios acima da fonte.

Na raiz `fc26-switch`:

```sh
venv/bin/python tools/rota_robusta.py prova_update --bin work/build-update/fc26-native
venv/bin/python tools/rota_robusta.py prova_30 --bin work/build-nxport/fc26-native --profile
venv/bin/python tools/rota_robusta.py prova_60 --bin work/build-nxport/fc26-native --fps60 --profile
```

Escolha um nome novo em cada tentativa. Por padrão, um jogo já aberto causa
recusa, sem comandos. `--wait-idle` permite entrar na fila do lançador; o
`boot_gpu.sh` aguarda a trava e verifica de novo que não há jogo aberto antes
de iniciar o binário. Nunca se deve remover a trava para forçar a execução.

`--warm-timeout 900` limita o aquecimento a 900 segundos a partir do PID
próprio. `--slot-timeout 1800` limita a espera até o boot próprio. A marcação
N/N do log precisa aparecer antes de qualquer tecla. O tempo não confirma
uma tela: a rota tira foto e exige texto esperado; telas desconhecidas ficam
em espera limitada e depois causam falha. No menu principal, mede o brilho
da seleção e corrige com cima/baixo até Pontapé de Saída. O aviso dos
servidores EA é uma etapa explícita, com foto e confirmação.

As referências em `work/rota-referencias` são criadas após o reconhecimento
do texto esperado. Em usos seguintes, o recorte da mesma identificação é
comparado com a referência (diferença média máxima de 14% por canal).
A primeira calibração fica registrada como `referencia_criada_apos_OCR`.
Essa calibração usa o texto local como prova inicial; não equivale a uma
comparação com uma referência anterior. Fotos não entram no repositório.
Se houver mudança legítima de idioma ou layout, guarde a pasta antiga com
outro nome antes de calibrar novamente; não aumente o limite para esconder
divergências. Telas de idioma/layout não reconhecidos falham visivelmente.

Só depois de duas fotos com o relógio crescente começa a medição. Uma
sequência de 16 quadros é pedida antes de ligar a coleta de GPU, para medir
o intervalo sem ela. `--profile` pede 600 quadros e recusa coleta incompleta
ou marcações inválidas. Fotos continuam durante 45 segundos. O relógio
precisa avançar também nesse período. Cada captura registra o relógio e a
hora real; reposições e pausas precisam ser consideradas ao calcular a
velocidade, e não se deve atribuir uma foto de menu a uma partida.

Os arquivos `work/logs/NOME_route.jsonl` e `NOME_controller.out` registram
as decisões. `boot_NOME.log` é o log do jogo, `NOME_step_*.png` são as fotos,
com leitura em `.ocr.json`, e `NOME.tsv` contém a coleta de GPU. O programa
encerra com saída 1 em falhas. Ele termina com `close`, aguarda 15 segundos
e encerra somente seus PIDs remanescentes, registrando cada um. O lançador
é iniciado em sessão própria; SIGINT/SIGTERM passam pela limpeza, incluindo
filhos de `lockf` e do observador. SIGKILL no próprio controlador, como em
qualquer programa, não permite executar o tratamento de saída.

Para conferir a segurança sem abrir o jogo:

```sh
venv/bin/python rev/nxport/tools/test_rota_robusta.py
```

Para gerar as quinze etapas mais caras de uma coleta:

```sh
venv/bin/python rev/nxport/tools/rank_nxport_gpu.py work/logs/prova_30.tsv
```

Os tempos de etapas podem se sobrepor. A soma deles não mede ocupação total
nem economia garantida. A letra D mistura cálculo pedido pelo jogo e cópias
associadas; a separação precisa de inspeção adicional antes de otimizar.


Carreira e observação dos defeitos (branch fc26-defeitos):

```sh
venv/bin/python rev/defeitos/tools/rota_carreira.py NOME
venv/bin/python rev/defeitos/tools/rota_carreira.py NOME --verify 12/8/2025
venv/bin/python rev/defeitos/tools/rota_carreira.py NOME --verify 12/8/2025 --inspect
venv/bin/python rev/defeitos/tools/defeitos_entrada.py NOME --bin work/build-defeitos/fc26-native --wait-idle
```

Esses roteiros usam `user-data-defeitos-carr` e o cache de `build-defeitos`.
`PARAR_defeitos` encerra com limpeza; na consulta `--inspect`, `NOME_FECHAR`
termina as fotos e fecha. A prova de partida inteira desta rodada foi feita
com `observar_carreira.py` e ações conferidas por foto. A reabertura e a data
do save foram verificadas automaticamente por `rota_carreira.py`; os estados
de partida e gravação desse roteiro foram derivados das telas observadas,
mas ainda não passaram juntos por outra partida inteira automática. Não
confundir a prova manual completa com validação integral dessa automação.

Em `defeitos_entrada.py`, `FC26_KITS_TODOS=1` fotografa as duas opções de
cada equipe e restaura a seleção inicial. `FC26_RODA_SALTAR=1` salta a
abertura segurando confirmar; `FC26_RODA_PULSOS=1` usa dois toques curtos
a cada 20 segundos durante a observação. As opções são diagnósticas.
Sem elas, observa a apresentação sem saltar. Imagens ficam fora do git.
