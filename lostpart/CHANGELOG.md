# Changelog

Todas as mudanças relevantes deste projeto ficam registradas aqui.  O formato
segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

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
