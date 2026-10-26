"""Textos do programa em português do Brasil.

Todas as mensagens que chegam ao usuário passam por aqui, para que o
vocabulário seja consistente e para que a tradução fique num único lugar.
O código, os nomes das funções e as mensagens de log continuam em inglês.
"""

from __future__ import annotations

__all__ = ["t", "MESSAGES", "format_size", "sector_number"]


#: Chave -> texto.  Os placeholders usam a sintaxe do ``str.format``.
MESSAGES: dict[str, str] = {
    # -- identidade ------------------------------------------------------
    "app.name": "lostpart",
    "app.tagline": "Encontre e recupere partições perdidas",
    "app.description": (
        "O lostpart procura sistemas de arquivos que continuam no disco mas "
        "perderam a entrada na tabela de partições, e reconstrói essa entrada."
    ),

    # -- interface gráfica ----------------------------------------------
    "gui.welcome.title": "Bem-vindo ao lostpart",
    "gui.welcome.subtitle": "Encontre partições perdidas e recupere o acesso aos seus arquivos.",
    "gui.welcome.start": "Procurar partições perdidas",
    "gui.welcome.how": "Como funciona",
    "gui.welcome.step1": "1. Escolha o disco que quer examinar.",
    "gui.welcome.step2": "2. O lostpart procura sistemas de arquivos no espaço livre.",
    "gui.welcome.step3": "3. Revise o que foi encontrado e recupere o que quiser.",
    "gui.welcome.safety": (
        "Nada é gravado no disco sem a sua confirmação, e um backup da tabela "
        "de partições é sempre feito antes de qualquer alteração."
    ),
    "gui.disk.title": "Escolha o disco",
    "gui.disk.subtitle": "Selecione o disco que você quer examinar.",
    "gui.disk.table": "Tabela",
    "gui.disk.partitions": "Partições",
    "gui.disk.free": "Espaço livre",
    "gui.disk.empty": "Nenhum disco pôde ser aberto. Execute como administrador para acessar os discos do sistema.",
    "gui.disk.refresh": "Atualizar",
    "gui.scan.title": "Procurando partições",
    "gui.scan.subtitle": "Isso pode levar alguns minutos em discos grandes.",
    "gui.scan.working": "Procurando…",
    "gui.scan.idle": "Aguardando…",
    "gui.scan.done": "Busca concluída",
    "gui.results.title": "O que encontramos",
    "gui.results.subtitle": "Partições encontradas no espaço livre do disco.",
    "gui.results.none": (
        "Nenhuma partição perdida foi encontrada neste disco. "
        "Isso pode significar que tudo está em ordem."
    ),
    "gui.results.column": "Início",
    "gui.results.size": "Tamanho",
    "gui.results.filesystem": "Sistema de arquivos",
    "gui.results.confidence": "Confiança",
    "gui.results.preview": "Pré-visualizar arquivos",
    "gui.results.recover": "Recuperar esta partição",
    "gui.results.back": "Voltar",
    "gui.preview.title": "Conteúdo da partição",
    "gui.preview.subtitle": "Os arquivos são lidos sem alterar nada no disco.",
    "gui.preview.empty": "Esta partição não pôde ser lida.",
    "gui.preview.open": "Abrir no Explorer",
    "gui.recover.title": "Recuperar a partição",
    "gui.recover.subtitle": "A entrada que falta será recriada na tabela de partições.",
    "gui.recover.what": "O que vai acontecer",
    "gui.recover.step1": "Um backup da tabela de partições atual será salvo.",
    "gui.recover.step2": "A entrada da partição será escrita de volta.",
    "gui.recover.step3": "O sistema operacional passa a enxergar a partição novamente.",
    "gui.recover.backup": "Fazer backup antes de escrever (recomendado)",
    "gui.recover.confirm": "Sim, recuperar a partição",
    "gui.recover.cancel": "Cancelar",
    "gui.recover.done.title": "Partição recuperada",
    "gui.recover.done.body": "A entrada foi escrita na tabela de partições.",
    "gui.recover.done.next": "O que fazer agora",
    "gui.recover.done.hint": (
        "Abra o Gerenciador de Discos do Windows para ver a partição. "
        "Se ela ainda não aparecer, clique com o botão direito nela e "
        "escolha 'Anexar' ou 'Importar'."
    ),
    "gui.recover.done.close": "Fechar",
    "gui.admin.title": "Permissões insuficientes",
    "gui.admin.body": (
        "Para ler e escrever discos, o lostpart precisa ser executado como "
        "administrator."
    ),
    "gui.admin.elevate": "Executar como administrador",
    "gui.admin.later": "Continuar sem Elevated (somente leitura)",
    "gui.common.next": "Avançar",
    "gui.common.back": "Voltar",
    "gui.common.cancel": "Cancelar",
    "gui.common.close": "Fechar",
    "gui.common.choose_disk": "Escolher disco",
    "gui.common.scanning": "Procurando…",
    "gui.common.menu": "Menu principal",

    # -- linha de comando ------------------------------------------------
    "cli.description": "Encontre e recupere partições perdidas.",
    "cli.usage.tail": "Sem comando, o lostpart abre o menu interativo.",
    "cli.command.list": "listar discos e tabelas de partições",
    "cli.command.scan": "procurar partições perdidas no espaço livre",
    "cli.command.recover": "recrever a entrada que falta na tabela",
    "cli.command.browse": "ver o conteúdo de uma partição",
    "cli.command.backup": "salvar a tabela de partições",
    "cli.command.restore": "restaurar uma tabela de partições salva",
    "cli.command.gui": "abrir a interface gráfica",
    "cli.help.device": "disco a examinar (número, caminho ou imagem)",
    "cli.help.mode": "profundidade da busca (full/quick)",
    "cli.help.checkpoint": "arquivo de checkpoint do SQLite",
    "cli.help.json": "mostrar o resultado em JSON",
    "cli.help.quiet": "não mostrar o progresso",
    "cli.help.start": "primeiro setor da partição recuperada",
    "cli.help.size": "tamanho da partição em setores",
    "cli.help.fs": "tipo de sistema de arquivos",
    "cli.help.bootable": "marcar a partição como ativa",
    "cli.help.apply": "gravar de verdade (sem esta opção nada é alterado)",
    "cli.help.no_backup": "não criar backup antes de gravar",
    "cli.help.backup_dir": "pasta onde o backup é salvo",
    "cli.help.path": "dentro da partição",
    "cli.help.mount": "montar a partição pelo sistema operacional",
    "cli.help.output": "arquivo de saída",
    "cli.help.backup": "arquivo de backup",

    # -- listagem de discos ----------------------------------------------
    "list.title": "Discos",
    "list.size": "Tamanho",
    "list.sectors": "Setores",
    "list.table": "Tabela",
    "list.none": "Nenhum disco pôde ser aberto. Execute como administrador para acessar os discos do sistema.",
    "list.no_table": "sem tabela de partições",
    "list.disk_guid": "GUID do disco",
    "list.crc_header": "CRC do cabeçalho",
    "list.crc_entries": "CRC das entradas",
    "list.crc_ok": "válido",
    "list.crc_bad": "inválido",
    "list.columns": ("#", "Início", "Setores", "Tamanho", "Tipo", "Ativa", "Lógica"),

    # -- varredura --------------------------------------------------------
    "scan.device": "Disco",
    "scan.table": "Tabela",
    "scan.mode": "Modo",
    "scan.time": "Tempo",
    "scan.free": "Espaço livre",
    "scan.regions": "{count} região(ões), {size} analisados",
    "scan.mode_full": "completa",
    "scan.mode_quick": "rápida",
    "scan.none": "Nenhuma partição perdida foi encontrada neste disco.",
    "scan.found": "Partições encontradas",
    "scan.columns": ("Início", "Setores", "Tamanho", "Sistema de arquivos", "Confiança", "Como foi identificada"),
    "scan.evidence": "Por que encontramos esta partição",
    "scan.progress": "Procurando no setor {sector}",
    "scan.source_boot": "assinatura de boot",
    "scan.source_bitmap": "assinatura + bitmap de alocação",

    # -- pré-visualização -------------------------------------------------
    "browse.filesystem": "Sistema de arquivos",
    "browse.method": "Como foi lido",
    "browse.method_internal": "leitura direta, sem alterar o disco",
    "browse.method_native": "montado pelo sistema operacional",
    "browse.mount_point": "Ponto de montagem",
    "browse.columns": ("Tipo", "Nome", "Tamanho"),
    "browse.not_found": "Não foi possível reconhecer um sistema de arquivos neste ponto.",
    "browse.no_fs": "Nenhum sistema de arquivos compatível foi reconhecido no setor {sector}.",
    "browse.entries": "{count} itens em {path} ({label})",
    "browse.mounted": "Montado em {target} ({count} itens)",

    # -- recuperação ------------------------------------------------------
    "recover.detected": "Sistema de arquivos detectado: {fs} ({label})",
    "recover.none": "Nenhum sistema de arquivos foi reconhecido no setor informado.",
    "recover.dry_run": "Nada foi gravado. Use --apply para escrever a entrada na tabela de partições.",
    "recover.backup": "Backup salvo em {path}",
    "recover.done": "Entrada gravada na tabela {table} ({kind}) a partir do setor {start}.",
    "recover.write_gpt": "Escrevendo a entrada GPT e atualizando as duas cópias da tabela…",
    "recover.write_mbr": "Escrevendo a entrada MBR…",
    "recover.would_write": (
        "Seria gravada uma entrada {table} para {fs} a partir do setor {start} "
        "({sectors} setores, {size})."
    ),
    "recover.wrote": (
        "Entrada {table} gravada na vaga {index} para {fs} ({label}), "
        "a partir do setor {start}."
    ),

    # -- backup ------------------------------------------------------------
    "backup.done": "Backup salvo em {path} ({chunks} trecho(s), tabela {kind}).",
    "restore.done": "Restaurados {bytes} bytes de {source} para {target}.",

    # -- menu interativo ---------------------------------------------------
    "menu.title": "lostpart {version} - encontre e recupere partições perdidas",
    "menu.1": "Listar os discos e suas partições",
    "menu.2": "Procurar partições perdidas em um disco",
    "menu.3": "Ver o conteúdo de uma partição",
    "menu.4": "Salvar a tabela de partições de um disco",
    "menu.5": "Abrir a interface gráfica",
    "menu.6": "Mostrar as opções da linha de comando",
    "menu.0": "Sair",
    "menu.select": "Escolha uma opção: ",
    "menu.back": "Pressione Enter para voltar ao menu…",
    "menu.bye": "Até logo!",
    "menu.unknown": "Opção desconhecida. Escolha um número entre 0 e 6.",
    "menu.device": "Disco (número, caminho ou imagem de disco): ",
    "menu.device_scan": "Disco a examinar: ",
    "menu.mode": "Profundidade da busca (full/quick) [full]: ",
    "menu.start": "Primeiro setor da partição: ",
    "menu.path": "Pasta dentro da partição (vazio para a raiz): ",
    "menu.output": "Arquivo de backup [lostpart-backup.json]: ",
    "menu.error": "Não foi possível concluir a operação: {error}",

    # -- erros -------------------------------------------------------------
    "error.generic": "Ocorreu um erro: {error}",
    "error.no_table": "Este disco não tem tabela de partições.",
    "error.no_device": "Não foi possível abrir o disco informado.",
    "error.readonly": "O disco é somente leitura; não é possível gravar.",
    "error.overlap": "A partição candidata sobrepõe a partição {index} (setores {start} a {end}).",
    "error.no_size": "O tamanho da partição é desconhecido; a entrada precisa de um comprimento.",
    "error.out_of_range": "A partição termina no setor {end}, mas o disco tem apenas {total} setores.",
    "error.no_slot": "A tabela MBR não tem vaga livre e não há partição estendida para aumentar.",
    "error.gpt_full": "A tabela GPT não tem vaga livre para uma nova entrada.",
    "error.installer": "É preciso rodar como administrador para acessar os discos do sistema.",
    "error.start_zero": "A partição candidata começa no setor 0, que guarda a tabela de partições.",
    "error.mbr_full": (
        "A tabela MBR não tem vaga livre e não há partição estendida para aumentar; "
        "converta o disco para GPT ou apague uma partição antes."
    ),
    "error.ebr_chain": "Não foi possível ler a cadeia de registros de boot estendidos.",
    "error.ebr_room": "Não há espaço livre dentro da partição estendida.",
    "error.ebr_fit": "A partição candidata não cabe dentro da partição estendida.",
    "error.gpt_header": "Não foi possível ler o cabeçalho da GPT.",
    "error.open_device": "Não foi possível abrir o disco {path}: {error}",
    "error.access_denied": (
        "O acesso a {path} foi negado; execute o programa como administrador."
    ),
    "error.numeric_device": (
        "Indicar o disco por número só funciona no Windows e no Linux."
    ),
    "error.empty_device": "Nenhum disco foi informado.",
    "error.unknown_device": "Não foi possível reconhecer o disco {spec}.",
    "error.mount_unsupported": "Montar a partição não é possível neste sistema.",
    "error.mount_no_path": "Este disco não expõe um caminho que possa ser montado.",
    "error.mount_failed": "Não foi possível montar a partição: {error}",
    "error.mount_point": "Não foi possível criar o ponto de montagem {target}: {error}",
    "error.mount_missing": "O comando '{command}' não está disponível neste sistema.",
    "error.no_volume": (
        "O Windows não expôs um volume para esta partição; talvez a entrada "
        "precise ser gravada e o disco verificado de novo."
    ),
    "error.browse_failed": "Não foi possível ler o conteúdo de {path}: {error}",
}


def t(key: str, **kwargs: object) -> str:
    """Devolve o texto da mensagem ``key``, formatado com ``kwargs``.

    Uma chave desconhecida devolve a própria chave, o que torna os erros de
    digitação visíveis de imediato em vez de silenciosos.
    """
    text = MESSAGES.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def format_size(size: int | float) -> str:
    """Formata um tamanho em bytes de forma legível."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0 or unit == "PB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def sector_number(message: str) -> str:
    """Extrai o número do setor de uma mensagem de progresso.

    O scanner informa o progresso em inglês (``scanning sector 1234``); quem
    mostra a mensagem ao usuário usa esta função para montar o texto no
    idioma do programa.
    """
    for token in message.replace(":", " ").replace(",", " ").split():
        if token.isdigit():
            return token
    return message
