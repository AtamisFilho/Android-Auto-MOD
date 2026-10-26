# Changelog

Todas as mudanças relevantes deste projeto ficam registradas aqui.  O formato
segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [0.3.1] — 2026-10-26

Esta versão não traz nada novo: ela conserta o que a revisão adversarial dos
commits da 0.3.0 encontrou.  Os defeitos abaixo eram **gravados** — alguns
deles corrompiam a tabela de partições do disco.

### Fixed

- **A GPT de reserva era gravada um setor acima do lugar certo.**  O vetor de
  entradas da cópia de reserva ocupa os setores imediatamente anteriores ao
  cabeçalho de reserva; com o cálculo antigo ele começava um setor depois e
  terminava **por cima do próprio cabeçalho**.  Toda recuperação em disco
  GPT deixava a tabela de reserva com o último entrada do vetor destruída e o
  CRC do vetor inválido.  O mesmo cálculo errado aparecia na leitura da
  reserva e na gravação do backup.
- **Uma GPT com entradas mais largas que 128 bytes era corrompida.**  A
  entrada gravada tem 128 bytes; quando a vaga do vetor é maior, o resto
  ficava para trás e o vetor *encurtava* — deslocando todas as entradas
  seguintes e invalidando o CRC do cabeçalho.  Agora a entrada é completada
  com zeros até a largura da vaga.
- **O número de entradas da GPT não tinha limite.**  Ele vem do disco, e um
  cabeçalho corrompido podia declarar quatro bilhões de entradas e fazer o
  programa tentar ler meio terabyte.  O número e o tamanho da entrada agora
  são verificados antes da leitura, com mensagens claras em vez de uma
  leitura descontrolada.
- **Um backup de outro disco era restaurado sem nenhuma verificação.**  O
  `restaurar` escrevia a tabela do disco A em cima do disco B, destruindo a
  tabela do B.  Agora o tamanho de setor é comparado, uma diferença no
  número de setores é avisada, e existe `--force` para quem quiser
  restaurar assim mesmo.
- **Um backup incompleto era restaurado pela metade.**  Um trecho com menos
  bytes do que o declarado era gravado, deixando metade do setor escrito e
  metade intacto — pior do que não restaurar.  O arquivo agora é conferido
  antes de qualquer escrita.
- **Um candidato descartado sumia sem deixar rastro.**  Quando dois
  candidatos ocupavam os mesmos setores, o menos confiante era descartado
  em silêncio, e o usuário não podia distinguir "não encontrei nada" de
  "encontrei e descartei".  Os descartados agora são relatados, com o
  motivo, na linha de comando e na interface gráfica.
- **Uma entrada de GPT corrompida produzia espaço livre sobreposto.**  Uma
  entrada cujo último LBA é menor que o primeiro tem tamanho negativo, e o
  cálculo do espaço livre devolvia regiões que se cobriam — o scanner lia os
  mesmos setores duas vezes e acreditava que eram espaço livre.  Entradas
  quebradas agora têm tamanho zero e são ignoradas.
- **O tipo do sistema de arquivos desconhecido era gravado como NTFS.**  Uma
  partição que declara o tipo errado é montada errada, ou não é montada
  nenhuma, e o usuário não tem como saber que a recuperação falhou.  Agora a
  recuperação é recusada com uma mensagem clara.
- **Um handle de disco físico ficava aberto.**  Na listagem de discos, o
  handle era fechado só no caminho feliz; quando a tabela não podia ser lida
  ou o disco não tinha tabela, o handle ficava aberto e segurava o disco pelo
  resto da sessão.  O mesmo acontecia quando a consulta de geometria do disco
  falhava logo depois de abrir o handle.
- **A retomada de varredura não existia.**  O `--checkpoint` gravava os
  resultados no fim da varredura e nunca lia nada de volta: a documentação
  prometia uma coisa que o código não fazia.  Agora o progresso é gravado
  durante a varredura, a próxima execução continua do ponto em que parou e
  os candidatos já encontrados são preservados.
- **Um candidato perdia o tamanho de setor ao passar pelo checkpoint.**  O
  tamanho da partição passava a ser calculado com 512 bytes por setor mesmo
  em disco de 4 Kn.
- **As colunas do checkpoint podiam ser escolhidas por quem chamasse a
  função.**  Elas entram na instrução SQL; agora só um conjunto conhecido de
  colunas é aceito.
- **A tela da interface gráfica subia o programa com administrador
  montando um comando de shell.**  Um caminho com aspas ou ponto e vírgula
  quebrava o comando, ou pior, mudava o que era executado.  A elevação usa
  agora `ShellExecuteW`, que não passa por interpretador de comando.
- **O console quebrava com uma linha de tamanho diferente do cabeçalho.**  Um
  `IndexError` derrubava a listagem inteira.
- **A evidência do bitmap podia ser falsa.**  Quando não havia setores
  antes do candidato para conferir, o programa afirmava mesmo assim que eles
  estavam vazios.
- **Propriedades que diziam "bytes" devolviam setores.**  `size_bytes`, na
  partição e na região de espaço livre, devolvia a contagem de setores — o
  mesmo tipo de erro que já tinha sido corrigido no candidato.  As duas
  propriedades foram removidas, por não serem usadas e por mentirem.

### Added

- **42 testes** concentrados nos caminhos que *recusam* algo — sobreposição,
  partição sem tamanho, candidato fora do disco, tabela cheia, disco somente
  leitura, entrada corrompida, backup de outro disco, backup truncado,
  retomada de varredura.  São os caminhos que um teste de caminho feliz
  nunca toca, e onde os defeitos acima estavam escondidos.

## [0.3.0] — 2026-10-26

Esta versão é sobre **linguagem**.  O lostpart foi escrito em inglês, do
começo ao fim, e quem precisa de recovering de partição não deveria precisar
ler inglês nem entender o jargão de disco para usar a ferramenta.

### Added

- **Interface gráfica completa** (`lostpart grafica`, ou a opção 5 do menu).
  Um assistente de sete telas em Tkinter, sem dependência fora da biblioteca
  padrão: *boas-vindas → escolha do disco → procurando → o que encontramos →
  pré-visualização → recuperar → concluído*.  A varredura roda em uma thread
  separada, então a janela nunca congela.
  - A tela de resultados mostra, lado a lado, o setor de início, o tamanho,
    o sistema de arquivos e a **confiança** de cada achado, com as evidências
    disponíveis para consulta.
  - A pré-visualização lê os arquivos da partição candidata **sem alterar
    nada no disco** e sem precisar de administrador.
  - A tela de recuperação explica em três linhas o que vai acontecer, com a
    opção de backup marcada de fábrica.
  - Quando faltam privilégios, uma faixa no rodapé explica isso e oferece o
    botão **Executar como administrador**, que reabre o programa já elevado.
- **Catálogo de textos em português** (`lostpart/i18n.py`), fonte única de
  verdade para todas as mensagens do programa, da interface gráfica, do
  console e das exceções.
- **Console redesenhado** (`lostpart/ui/console.py`): painéis com moldura,
  tabelas de colunas alinhadas, rótulos e valores alinhados, barra de
  progresso de uma linha e marcadores de sucesso, aviso e erro.
- **Subcomandos em português** na linha de comando — `listar`, `escanear`,
  `recuperar`, `navegar`, `backup`, `restaurar` e `grafica` — cada um
  aceitando também o nome em inglês, para que scripts antigos continuem
  funcionando.
- **Captura de tela de todas as telas da interface**
  (`scripts/screenshot_gui.py`), usada para conferir o visual e para
  documentar o projeto.
- **Novos testes** para o catálogo de textos, para o renderizador do console e
  um *smoke test* da interface gráfica, que é pulado automaticamente quando
  não há display disponível.

### Changed

- O `README.md` foi reescrito em português e agora traz as capturas de tela da
  interface, o passo a passo para quem não conhece o assunto e a referência
  técnica da linha de comando.
- A ajuda do `argparse` passou a sair em português: `uso:`, `comandos:`,
  `opções:`.
- O modelo de candidato passou a guardar o tamanho do setor do dispositivo, e
  `size_bytes` devolve o tamanho **em bytes** — antes ele devolvia a contagem
  de setores, e a interface mostrava um tamanho 512 vezes menor que o real.

### Fixed

- O `dist/SHA256SUMS.txt` era um arquivo órfão, escrito uma vez e nunca mais
  regenerado — a versão 0.3.0 chegou a publicar a lista de checksums da 0.2.0
  ao lado dos binários novos.  O `scripts/build.py` agora reescreve a lista a
  cada build, e o `scripts/verify_release.py` confere cada checksum contra o
  arquivo correspondente, que é o que teria pegado isso.
- As telas da interface usavam `place` com o `anchor` padrão (`center`), o que
  centralizava cada rótulo em vez de alinhá-lo no canto superior esquerdo.  A
  tela inicial ficava com o título cortado e o botão fora da janela.  O
  layout da janela passou a usar `grid` (determinístico) e o cartão de
  boas-vindas passou a usar `pack`.
- O botão *Pré-visualizar* era cortado pela tabela de resultados; os botões
  ganharam uma barra própria no rodapé do quadro.
- A saída redirecionada para arquivo ou pipe quebrava em caracteres de
  moldura, que não existem na codificação local (cp1252 no Brasil).  Quando a
  saída não é um console, ela passa a ser gravada em UTF-8.
- A mensagem de progresso da varredura aparecia duplicada no console
  (*"Procurando no setor scanning sector 1234"*).
- As mensagens de erro que chegam ao usuário — sobreposição de partição,
  tabela sem vaga, disco somente leitura, falha ao abrir um disco, falha ao
  montar — passaram a ser exibidas em português.

## [0.2.0] — 2026-10-25

### Added

- **Menu interativo.**  Iniciado sem comando, o `lostpart` abre um menu que
  conduz as mesmas operações.  O build 0.1.0 do Windows não fazia nada em um
  duplo clique: a janela do console abria, imprimia o texto de uso e fechava
  em milissegundos.  Quando o console foi criado só para o programa — a
  assinatura de um duplo clique no gerenciador de arquivos — o programa agora
  espera uma tecla antes de fechar.
- **Instalador para Windows** (`lostpart-installer.exe`), feito com Inno Setup.
  Instala por usuário, então nunca pede direitos de administrador, e traz os
  atalhos do menu Iniciar, a opção de adicionar o programa ao PATH, a entrada
  em *Programas e Recursos* e um desinstalador que funciona.
- **Ícone do aplicativo**, gerado por `scripts/make_icon.py`: um disco
  dividido em setores com um setor destacado.
- **Script de verificação** (`scripts/verify_release.py`) que confere os
  artefatos produzidos: os cabeçalhos PE e ELF, o *trailer* do payload, o
  conteúdo do payload e as permissões do interpretador embutido.

### Changed

- A interface de linha de comando foi dividida em operações reutilizáveis
  (`list_devices_text`, `scan_device_text`, `browse_partition_text`,
  `backup_table_text`) usadas tanto pelos comandos quanto pelo menu interativo.
- O script de build ganhou um alvo `installer` e escreve a versão dentro do
  script do instalador, para que os dois nunca fiquem defasados.

### Fixed

- Uma marca de ordem de bytes canalizada para o menu interativo é removida,
  tanto na forma UTF-8 quanto na forma da página de códigos 1252.

## [0.1.0] — 2026-10-25

Primeira versão.

### Added

- **Acesso direto ao disco** no Windows (`\\.\PhysicalDriveN` com
  `DeviceIoControl`), no Linux (`/dev/sdX` com `ioctl`) e em imagens de disco.
  O tamanho do setor lógico informado pelo disco é usado em todo o programa,
  então discos 512e (Advanced Format) e 4Kn são tratados corretamente.
- **Suporte a tabelas de partições** MBR — incluindo a cadeia de registros de
  boot estendidos — e GPT, com codificação de GUID, verificação por CRC32 e
  cópias primária e de reserva consistentes.
- **Cálculo do espaço livre**: as lacunas entre as partições conhecidas, que
  são os lugares onde uma partição perdida pode se esconder.
- **Sondas de sistema de arquivos** para NTFS, exFAT, FAT12/16/32, ext2/3/4,
  Linux swap e HFS+.  Todo candidato é analisado campo a campo em vez de ser
  aceito só pela sua assinatura.
- **Prova dos limites do NTFS** pelo meta-arquivo de alocação `$Bitmap`: o
  mapa é conferido contra os bytes reais do disco, o que confirma o início do
  volume e determina onde ele termina.  O `$MFT` é usado como contraprova e os
  setores anteriores ao candidato são amostrados para confirmar que pertencem
  a outro volume.
- **Varredura** com um modo rápido e um completo, informando a confiança e os
  motivos concretos por trás de cada candidato.
- **Checkpoints retomáveis** apoiados em SQLite.
- **Gravação conservadora**: ensaio por padrão, um backup automático das
  estruturas da tabela de partições antes de cada gravação, validação que
  recusa candidatos sobrepostos ou fora dos limites, extensão da cadeia de
  registros de boot estendidos quando não há vaga livre na MBR, e uma
  atualização da GPT que mantém as duas cópias e todos os CRCs consistentes.
- **Navegação somente-leitura** de um candidato sem montá-lo, além da
  montagem nativa opcional (letra de unidade no Windows, loop mount no Linux).
- **Interface de linha de comando** com `list`, `scan`, `recover`, `browse`,
  `backup` e `restore`.
- **Binários avulsos** para Windows x64 e Linux x64.
- **Suíte de testes** com 76 testes construídos sobre imagens de disco
  sintéticas: setores MBR, discos GPT com as duas cópias e um volume NTFS
  completo com `$MFT` e `$Bitmap` de verdade.  Nenhum disco físico é tocado
  pelos testes.

[0.1.0]: https://github.com/AtamisFilho/testes/releases/tag/v0.1.0
[0.2.0]: https://github.com/AtamisFilho/testes/releases/tag/v0.2.0
[0.3.0]: https://github.com/AtamisFilho/testes/releases/tag/v0.3.0
[0.3.1]: https://github.com/AtamisFilho/testes/releases/tag/v0.3.1
