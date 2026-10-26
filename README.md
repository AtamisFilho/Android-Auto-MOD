# Aircross Cockpit 🚗

**App pessoal para Citroën C4 Aircross 2019 + Samsung S25 Ultra (sem root).**

> ### ⚠️ Conexão com o carro — leia primeiro
> A central do C4 Aircross 2019 só fala **MirrorLink** (não tem Android Auto), e o
> **S25 Ultra não tem servidor MirrorLink** (Samsung removeu o recurso do One UI;
> o padrão foi oficialmente encerrado pelo consórcio CCC em 2023). Portanto:
>
> | Caminho | Como | Qualidade | Funciona hoje? |
> |---|---|---|---|
> | **B · Pendrive USB** (recomendado) | App exporta os vídeos → player **nativo da central** toca do USB | Full | ✅ com o S25 Ultra + OTG |
> | **A · Celular antigo espelhado** | Galaxy S8/S9 (Android ≤ 9) roda o **Modo Espelho** → central espelha via MirrorLink | ~10–20 fps (VNC) | Precisa de um 2º celular |
> | **C · Trocar a central** | Central aftermarket c/ Android Auto → o app AA original volta 100% | Full | Compra futura |
>
> **Guia completo:** [`docs/GUIA_MIRRORLINK.md`](docs/GUIA_MIRRORLINK.md)

Um app exclusivo, do seu jeito, com:

| Função | Onde aparece | Como funciona |
|---|---|---|
| **Vídeos do WhatsApp** (recentes primeiro) | App "Aircross Cockpit" na grade de apps do AA | Vídeo em **tela cheia** na tela do carro, **somente com o carro parado** (sensor de velocidade) |
| **Vídeos do celular** (câmera, downloads etc.) | Idem | Idem |
| **Favoritos** (estrela no player) | Idem | Funciona para vídeos |
| **Músicas do celular** | Lista de apps de **mídia** do AA (junto ao Spotify) | Player nativo de mídia do AA, controles no volante, notificação com controles |
| **Áudios do WhatsApp** (mensagens de voz) | Idem | Ouça os áudios recebidos pelo alto-falante do carro |
| **Modo Espelho** (v1.1) | Player fullscreen na tela do **celular** (espelhado via MirrorLink ou suporte) | Trava de velocidade por **GPS** do próprio celular; alavancas gigantes p/ uso no carro |
| **Exportar p/ pendrive** (v1.1) | Player **nativo da central** lê o USB | MP4/H.264+AAC garantido; cada arquivo é **validado** p/ tocar também nos players nativos do celular |

> **YouTube:** intencionalmente **não** faz parte deste app (extrair vídeos do YouTube
> viola os termos de serviço da Google). Para YouTube na tela do carro, use o
> **Fermata Auto** — veja o guia na seção 6.

> **Instagram/TikTok:** não existem meios de exibir esses apps na tela do carro via
> Android Auto sem root (não há API pública e o espelhamento é bloqueado pela Google
> em versões atuais).

---

## 1 · Requisitos

- PC (Windows/Mac/Linux) com [Android Studio](https://developer.android.com/studio) — grátis, já vem com JDK 17.
- Cabo USB-C **de dados** para ligar o S25 Ultra ao carro.
- Android Auto instalado e atualizado no celular.
- ~2 GB de disco livre (Android Studio + dependências baixadas no 1º build).

## 2 · Compilar o APK

1. Instale o Android Studio (padrões sugeridos; escolha "Standard" no assistente).
2. Descompacte este projeto e abra a pasta `aircross-cockpit` no Android Studio
   (**File → Open** — a pasta que contém `settings.gradle.kts`).
3. Aguarde o **Gradle Sync** (baixa dependências na 1ª vez, ~5–10 min).
4. Menu **Build → Build App Bundle(s) / APK(s) → Build APK(s)**.
5. Ao terminar, clique em **locate** na notificação. O APK está em:
   `app/build/outputs/apk/debug/app-debug.apk`
   (o APK *debug* já é assinado e instalável — perfeito para uso pessoal).

### (Opcional) APK release assinado

```bash
keytool -genkey -v -keystore minha-chave.jks -keyalg RSA -keysize 2048 \
  -validity 10000 -alias cockpit
```

No `app/build.gradle.kts`, adicione dentro de `android { signingConfigs { ... } }`
e selecione a config em `buildTypes.release`. Guarde o `.jks` — **nunca** suba para o
repositório (já está no `.gitignore`).

## 3 · Instalar no S25 Ultra

1. Copie o `app-debug.apk` para o celular (Google Drive, cabo, etc.).
2. Toque no APK → "Instalar de fontes desconhecidas" (só na 1ª vez).
3. Abra **Aircross Cockpit** e toque em **Conceder permissões**
   (vídeos, músicas, notificações, localização — usada pela trava de GPS
   do Modo Espelho).
4. Use o **Testador de mídia** para conferir que a biblioteca aparece.

## 4 · Liberar o app na tela do carro (Android Auto — modo desenvolvedor)

Apps que não vêm da Play Store precisam do AA em modo desenvolvedor:

1. No celular, abra o app **Android Auto** → role até o fim → toque **10× em "Versão"**
   → "Você agora é um desenvolvedor".
2. Toque no menu **⋮ → Configurações do desenvolvedor**.
3. Ative **"Fontes desconhecidas"** (permite apps de tela, como este e o Fermata).
4. Entre no carro, ligue o USB-C — o AA abre sozinho.
5. Na grade de apps da tela do carro: **Aircross Cockpit** (vídeos) e, na lista de
   mídia: **Aircross Cockpit** (músicas/áudios, junto ao Spotify).

## 5 · Como o app se protege (e protege você)

- **Vídeo só parado:** o app lê o **sensor de velocidade** do carro via AA
  (`CarHardwareManager`). Carro andando → vídeo pausa sozinho.
- **Modo Espelho (v1.1):** sem Android Auto, a mesma trava usa o **GPS do celular**
  (`MotionGate.startGps`): acima de ~3 km/h o vídeo bloqueia com tela cheia.
- Se a sua central não reportar velocidade, o vídeo fica bloqueado até você ativar
  **"Permitir vídeo sem sensor"** no app do celular (use com consciência).
- **Áudio** (músicas/áudios WhatsApp) toca normalmente em movimento — igual Spotify.
- **Retomar:** cada mídia volta de onde parou (posição salva por arquivo).
- O vídeo usa a **Surface em tela cheia** do Car App Library (categoria
  NAVIGATION + `NavigationTemplate` + `AppManager.setSurfaceCallback`), **com recorte
  central** (`VIDEO_SCALING_MODE_SCALE_TO_FIT_WITH_CROPPING`).

## 6 · YouTube no carro — Fermata Auto (sem root)

O Fermata Auto é o player "comunitário" para AA que reproduz YouTube (e vídeos
locais/rede) na tela do carro **com o veículo parado**:

1. Baixe o APK **no site oficial do projeto** (fermataauto.com) — evite espelhos.
2. Instale no celular (fontes desconhecidas).
3. Conecte no carro — na grade de apps do AA aparece **Fermata**.
4. Abra → YouTube → escolha o vídeo. Reproduz apenas parado (comportamento padrão).
5. Na prática costuma rodar **sem anúncios** (usa stream direto) — mas não é algo
   que eu possa garantir em update futuro.

O modo desenvolvedor/fontes desconhecidas do item 4 da seção anterior é o mesmo.

## 7 · WhatsApp (mensagens por voz) — nativo do Android Auto

1. Android Auto → **Notificações** → ative **WhatsApp**.
2. Chegou mensagem → aparece na tela do carro; toque no microfone e responda por voz
   (ou use o botão de voz do volante).

## 8 · Bloqueio de anúncios no celular (opcional)

- **DNS privado:** Ajustes → Conexões → Mais redes → **DNS privado** →
  `dns.adguard-dns.com` — bloqueia anúncios na maioria dos apps/navegador.
- **Limitação honesta:** anúncios *dentro dos vídeos* do YouTube oficial **não são
  bloqueáveis por DNS** (vêm dos mesmos servidores do vídeo). No Fermata, via stream
  direto, normalmente não aparecem.
- Um YouTube 100% sem anúncios exigiria cliente modificado (ReVanced) — **violando os
  termos do YouTube**; fica a seu critério e risco, apenas no celular.

## 9 · Estrutura do projeto

```
app/src/main/java/com/atamisfilho/aircrosscockpit/
├── CockpitApp.kt                  Application global
├── car/                           App da TELA DO CARRO (Car App Library)
│   ├── CockpitCarAppService.kt    entry point (categoria NAVIGATION → Surface)
│   ├── CockpitSession.kt          sessão + sensor + ciclo de vida
│   ├── HomeScreen.kt              grade de pastas
│   ├── FolderScreen.kt            lista de arquivos da pasta
│   ├── PlayerScreen.kt            player (NavigationTemplate + Surface em tela cheia)
│   ├── MotionGate.kt              trava de movimento (sensor AA **ou** GPS)
│   ├── GpsSpeedProvider.kt        velocidade por GPS (Modo Espelho)
│   ├── VideoPlayerController.kt   ExoPlayer global (fila, favoritos, retomada)
│   └── CarIcons.kt                ícones
├── media/                         Biblioteca + app de MÍDIA do AA
│   ├── MediaRegistry.kt           scan MediaStore + pastas do WhatsApp
│   └── CockpitMediaService.kt     MediaLibraryService (media3)
├── phone/                          UI no CELULAR
│   ├── MainActivity.kt            permissões/checklist
│   ├── TestPlayerActivity.kt      testador de reprodução
│   ├── MirrorPlayerActivity.kt    Modo Espelho (player fullscreen + trava GPS)
│   └── ExportActivity.kt          exportação p/ pendrive (cópia/remux/verificação)
└── util/                          Prefs (favoritos/posições/pendrive), Format
```

## 10 · Solução de problemas

| Problema | Causa provável | Correção |
|---|---|---|
| App não aparece na grade do AA | Modo desenvolvedor/fontes desconhecidas desligado | Refaça a seção 4 |
| Aparece, mas vídeo fica preto | Central não entregou Surface (ou vídeo protegido DRM) | Teste um vídeo gravado pela câmera; se persistir, me avise |
| "Aguardando o sensor…" | Central não reporta velocidade | Ative "Permitir vídeo sem sensor" ou mantenha bloqueado |
| "Aguardando GPS" no Modo Espelho | Primeiro fix de GPS demora (local fechado) | Aguarde ao ar livre (~30 s) ou ative "Permitir vídeo sem sensor" |
| Central não lê o pendrive | Formato/pasta errados | FAT32 ≤ 32 GB, exporte p/ a pasta VIDEO — veja `docs/GUIA_MIRRORLINK.md` |
| Vídeo exportado toca no celular, não no carro | Codec pouco comum (HEVC) | Exporte de novo (relatório marca ⚠); teste com vídeo do WhatsApp |
| Pastas vazias | Permissões negadas | Abra o app no celular → Conceder permissões → Escanear |
| Erro de compilação em `MotionGate.kt` | Versão de lib diferente do previsto | Me mande a mensagem de erro — correção rápida |
| WhatsApp não aparece nas pastas | Pasta fora do padrão | Me diga o caminho (Gerenciador de arquivos) |

## 11 · Avisos

- **Uso pessoal:** apps com vídeo não são aceitos na **Play Store** (regras anti-distração
  da Google). Este projeto é para **instalação própria (sideload)**, o que é permitido.
- O vídeo usa APIs **públicas** do Car App Library (Surface de navegação) de forma que a
  Google não endossa para vídeo; **atualizações do Android Auto podem exigir ajustes**
  no app (é o mesmo risco que o Fermata corre).
- Vídeo em movimento é crime/violador de normas de trânsito e perigoso — por isso o
  sensor de velocidade trava por padrão.
- Mídias do WhatsApp: o app apenas **lê arquivos** já salvos no aparelho (nada sai do celular).

---

Projeto gerado para **AtamisFilho** · uso pessoal · sem garantias — peça suporte no chat
que gerou este app. 🚙
