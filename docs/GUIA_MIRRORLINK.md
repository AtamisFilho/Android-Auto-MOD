# Guia MirrorLink — Aircross Cockpit no C4 Aircross 2019

> **Situação em uma frase:** a central do carro só fala **MirrorLink**, o **S25 Ultra
> não sabe falar MirrorLink** (nem com app, nem com root), e nenhum código pode mudar
> isso. Este guia mostra os **três caminhos que funcionam de verdade** e como usar
> cada um com este app.

---

## 0 · As três verdades técnicas

**1. O S25 Ultra não tem — e nunca terá — servidor MirrorLink.**
MirrorLink não é um app: é um **servidor embutido no firmware do celular** (camada USB
+ certificado digital assinado pelo consórcio **CCC**, validado no pareamento com o
carro). A Samsung encerrou o suporte: os últimos com MirrorLink foram **S8–S10** (o
S10 perde o recurso ao atualizar para Android 10 / One UI 2; do S20 em diante nunca
existiu). O CCC oficializou o encerramento do padrão em 2023.

**2. Mesmo com celular compatível, o espelhamento tem limite.**
MirrorLink espelha a tela por **VNC** (quadro a quadro): na prática **~10–20 fps** com
compressão visível. Para navegar em listas, ótimo; para assistir filme, "assistível,
mas longe do fluido". O **áudio** sai limpo pelo cabo/Bluetooth do carro.

**3. O caminho Android Auto original continua válido — mas não neste carro.**
Sem host do Android Auto na central, o `CockpitCarAppService` nunca aparece na tela do
C4 Aircross. O código foi preservado intacto: se você trocar de central (caminho C) ou
de carro, tudo volta a funcionar (incluindo Fermata Auto).

---

## 1 · Caminho B — Pendrive USB (recomendado · funciona HOJE com o S25 Ultra)

A central do carro tem player **nativo** de vídeo por USB (com o carro parado).
O app exporta os vídeos prontos para ela.

### Do que precisa
- Pendrive **FAT32, ≤ 32 GB** (FAT32 aceita arquivos de até 4 GB — vídeos do WhatsApp
  ficam bem abaixo disso).
- Adaptador **USB OTG** para plugar o pendrive no S25 Ultra.

### Passo a passo
1. Plugue o pendrive no celular (OTG).
2. Abra **Aircross Cockpit → Exportar vídeos para o pendrive**.
3. **Escolher pendrive / pasta** → escolha o pendrive (de preferência a pasta `VIDEO`,
   que as centrais PSA costumam listar primeiro).
4. Toque em **Exportar os 20 mais recentes do WhatsApp** ou em vídeos individuais.
5. Leia o **relatório**: cada linha mostra o que foi gravado.
   - `✔ 001-nome.mp4 · 12,3 MB · carro ✓ · celular ✓` → perfeito: MP4/H.264+AAC,
     arquivo reaberto com sucesso e codec **testado contra os decoders nativos do
     celular** (garantia de que os players do celular — Galaxy/Meus Arquivos/Ficheiros —
     também tocam aquele arquivo direto do pendrive).
   - `⚠` → exportado com ressalva (HEVC/MP3/áudio descartado) — teste no carro antes
     de confiar.
   - `✖` → não exportado, com o motivo (codec incompatível, > 4 GB etc.).
6. Despluge o pendrive, plugue **na central do carro** e abra o player de mídia/USB
   com o carro parado.

### O que o app faz sozinho na exportação
- **Cópia direta** quando o arquivo já é MP4/H.264+AAC (vídeo do WhatsApp quase
  sempre é) — rápido e sem perda.
- **Remux sem recodificar** quando só o "empacotamento" precisa mudar (ex.: `.mkv`
  virando `.mp4`) — sem perda de qualidade.
- **Nomes compatíveis com FAT32**: sem acentos, espaços ou símbolos, numerados na
  ordem (`001-`, `002-`…) para a reprodução sequencial da central.
- **Áudio**: AAC entra; MP3 entra com aviso; AMR/Opus/Vorbis são descartados (anotado
  no relatório — melhor mudo do que travado).

### Teste de validação no carro (faça uma vez)
Exporte **um** vídeo do WhatsApp, plugue no carro e confirme que a central lista e
toca com o carro parado. Se tocar: o caminho B está confirmado e é o seu dia a dia.
Se a central exigir pasta específica, exporte para dentro dela (ex.: `VIDEO`).

---

## 2 · Caminho A — Celular antigo espelhado (MirrorLink de verdade)

Se você quiser o "tela do carro mostrando o app": é preciso um **celular certificado
MirrorLink** conectado por cabo no carro, rodando o **Modo Espelho** do app.

### Celulares que servem (Samsung, o mais fácil no Brasil)
| Modelo | Android máximo com MirrorLink |
|---|---|
| Galaxy S8 / S8+ | Android 9 (Pie) |
| Galaxy S9 / S9+ | Android 9 (Pie) |
| Galaxy Note8 / Note9 | Android 9 (Pie) |
| Galaxy S10e/S10/S10+ | Android 9 (**não atualize para o 10!**) |

> ⚠️ **Nunca atualize esse celular para Android 10+** — o MirrorLink é removido.
> Compre um usado "estocado" e deixe ele só para o carro.

### Preparando o celular antigo
1. Instale o mesmo APK do Aircross Cockpit (versão 1.1+).
2. Copie os vídeos para ele: via PC, ou exporte para o pendrive (caminho B) e depois
   copie os arquivos para a pasta `Download` do celular antigo — o app os encontra em
   **"Vídeos do celular"**.
3. Conceda as permissões (vídeos + **localização**, para a trava por GPS).

### Ligando no carro
1. No celular antigo: **Ajustes → Conexões → Mais definições de conexão →
   MirrorLink** (se não aparecer, o aparelho/firmware não tem servidor MirrorLink).
2. Pareie o **Bluetooth** do celular com o carro (o áudio sai por ali).
3. Conecte o **cabo USB** — a central mostra a tela espelhada.
4. Abra o ícone **Cockpit Player** (o Modo Espelho tem ícone próprio no launcher) e
   use: alavancas grandes, toques simples, lista → player.

### Segurança no Modo Espelho
Sem Android Auto não existe sensor do carro — então o app usa o **GPS do próprio
celular**: acima de ~3 km/h a tela trava ("Carro em movimento") e o vídeo pausa
sozinho. Em local fechado, sem fix de GPS, use "Permitir vídeo sem sensor" (no app
principal) por sua conta e risco.

### Expectativa honesta
- Listas e menus: fluidos o suficiente.
- Vídeo: **~10–20 fps** com compressão de tela — dá para assistir parado, mas não é
  a qualidade do caminho B. Áudio impecável via Bluetooth.
- Em movimento, a central pode bloquear apps não certificados no espelhamento
  (irrelevante no seu uso parado).

---

## 3 · Caminho C — Trocar a central (volta tudo ao 100%)

Uma central multimídia aftermarket **com Android Auto** (Positron, Pioneer, JVC,
Sony, entre outras — molduras específicas para o C4 Aircross existem no mercado)
devolve:
- O app **Android Auto original** completo (Surface em tela cheia, sensor de
  velocidade do carro, lista de mídia junto ao Spotify);
- **Fermata Auto** (YouTube) — que exige Android Auto.

Custo típico: aparelho + moldura + instalação. Se um dia isso acontecer, nada precisa
ser reprogramado: o lado Android Auto do app está intacto.

---

## 4 · Perguntas rápidas

**"Não existe app que faça o S25 Ultra 'virar' MirrorLink?"**
Não. O protocolo exige servidor no firmware + certificado por aparelho. Não há
implementação confiável nem com root; o padrão foi encerrado pelo CCC.

**"E espelhar o S25 Ultra por outros meios (Miracast/DeX)?"**
A central do carro não recebe nenhum deles — só MirrorLink e USB.

**"Os vídeos do pendrive aparecem na Galeria do celular?"**
Sim: são MP4/H.264 padrão. No S25 Ultra, abra **Meus Arquivos → pendrive** e toque —
o player nativo abre. O relatório de exportação marca `celular ✓` só quando o codec
foi confirmado contra os decoders do aparelho.

**"Por que 20 vídeos por vez?"**
Lote razoável para não lotar a tela de progresso. Toque em quantos quiser
individualmente — o relatório acumula tudo.

**"O app ainda instala no S25 Ultra?"**
Sim — o `minSdk 28` só **ampliou** a compatibilidade (Android 9+). Nada mudou para o
S25 Ultra.
