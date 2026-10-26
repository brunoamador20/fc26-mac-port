# Medição de GPU por etapa

O medidor fica desligado por padrão. Sem coleta, não cria memória de contadores,
não acrescenta comandos de GPU e não abre arquivos. Restam verificações pequenas
na CPU para permitir ligar a coleta durante a execução; isso não é uma promessa
de literalmente zero instruções de CPU.

Para coletar uma faixa de quadros, defina `DM_NVN_GPUPROF=4000-4599` e
`DM_NVN_GPUPROF_FILE=/caminho/absoluto/coleta.tsv` antes de abrir o jogo.
Com o arquivo de destino definido, também é possível enviar `flag gpuprof 600`
pelo arquivo de entrada para coletar os próximos 600 quadros. `flag gpuprof 0`
cancela a próxima faixa na fronteira entre envios. Use um arquivo novo por coleta.

Cada etapa recebe duas marcações do Metal 4, adaptadas do GPUPROF do nxnative
(`7a3b95873bf1836bf7f70e2e2e3245e1cabb1620`, MIT,
`third_party/d2r_gfx/LICENSE.nxnative`). A thread separada de desenho recebe as
marcações por sua fila de comandos. Cada parte enviada à GPU tem memória própria,
mantida viva até a conclusão; o medidor não reutiliza resultados ainda em uso.
No M1, uma etapa que apenas limpa destinos não escreve a marcação final de
fragmentos. Esse caso foi reproduzido sem dados do jogo: a marcação inicial era
válida e a final ficava em zero. Para essas limpezas, o medidor marca o fim no
objeto de envio depois de fechar a etapa, incluindo a gravação do resultado.
Na thread separada, essa marcação também é uma mensagem da nossa fila. O teste
real cobre limpeza, dois desenhos de cor e um desenho só de profundidade.

O limite é de 2.048 etapas por parte enviada. O log informa perdas e resultados
inválidos; uma coleta com perdas não deve ser apresentada como completa.

A coleta mantém a divisão dos envios, o compartilhamento das etapas de cálculo
e a thread de desenho. Ela não liga o medidor antigo `DM_NVN_PASSGPU`, nem o
outro diagnóstico `TOTK_PASS_GPU`, que altera esses caminhos durante a coleta.
Não combine os três para comparar desempenho.

As colunas, separadas por tabulação, são: quadro, identificador da etapa,
tipo, milissegundos, desenhos, largura, altura, oito formatos de cor,
formato de profundidade, quantidade de destinos de cor, cópias, cálculos,
primeiro shader. Os formatos são os valores de `MTLPixelFormat` do SDK.

Tipos:

- `R`: desenho pedido pelo jogo; com zero desenhos, limpeza de destinos.
- `D`: cálculo pedido pelo jogo. Pode compartilhar a etapa com cópias nossas;
  os contadores mostram essa mistura, sem atribuir toda sua duração ao cálculo.
- `B`: cópias nossas.
- `C`: cálculos/conversões nossos.
- `O`: conversões nossas feitas por desenho.
- `P`: apresentação da janela, incluindo sobreposições e eventual captura de tela.
- `U`: envio/conversão de texturas, que pode misturar tamanhos e formatos.

Nas cópias e nos cálculos, tamanho e formato correspondem ao primeiro destino de
textura observado. `0×0` indica buffers ou um lote misto sem destino único.
Os desenhos de `O` são contabilizados diretamente; os demais desenhos do jogo
usam a diferença do contador de desenhos da etapa. Cálculos indiretos podem não
aparecer no contador de chamadas diretas; sua duração continua na etapa.

`P` e `U` usam a duração do envio completo informada pelo Metal, sem acessar os
contadores da thread do jogo. Seu quadro é o quadro corrente observado no envio,
que pode diferir do quadro exibido pela fila da janela.

As marcações são relaxadas: as etapas podem se sobrepor. Sua soma não mede
ocupação exclusiva de GPU. Ordene os grupos para investigação e confirme cada
economia com imagens e uma coleta separada. Exclua os quadros de diagnóstico
das comparações de fps: medir também tem custo.

Para registrar somente o preparo de uma textura por desenho, use
`DM_NVN_PASSDUMP_RT=512x1024`. O filtro considera o tamanho base dos
destinos de cor e profundidade; os pedidos por quadro e pelo arquivo de
comandos continuam funcionando junto com ele. Isso permite capturar uma
etapa curta durante o carregamento sem registrar todos os menus. Como o
registro completo altera o caminho de diagnóstico, essas execuções não
servem como referência de velocidade. O filtro fica desligado por padrão.

Para comparar os bytes de origem de uma textura no caminho de envio com
reorganização pela GPU, use `DM_NVN_UPCHECK=512x1024`. O tamanho filtra as
texturas de origem. Cada linha `[upcheck]` contém apenas resumos numéricos:
`cpu` ao gravar a cópia, `gpu` dos bytes copiados pela GPU e `cpu_done` da
mesma faixa quando o envio termina. `same_begin` indica se o buffer escolhido
continua cadastrado para a faixa ao gravar a cópia; `same_buffer` faz essa
consulta ao terminar. Uma troca de buffer pode preservar todos os bytes.
Essas consultas são observações separadas, não uma trava do mapeamento;
igualdade nos três momentos não exclui uma mudança temporária entre eles.
O diagnóstico acrescenta cópias e pode mudar o tempo da reprodução.
Sem a variável, não há essas cópias nem consultas adicionais.

As texturas acompanhadas por hash usam uma cópia estável da origem durante o
envio. Nesse caso, `cpu` e `cpu_done` descrevem essa cópia, e a ausência dela
na tabela de pools (`same_begin=0`, `same_buffer=0`) é esperada. Para investigar
uma escrita temporária na memória original, use também o binário anterior
preservado e o teste real `probe-gpu-upload-batch`; só os resumos da cópia
estável não observam essa escrita.
