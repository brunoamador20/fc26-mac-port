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
