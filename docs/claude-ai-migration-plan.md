# Claude.ai migration plan

Дата проверки документации: 2026-04-29

## Что важно про Claude apps / custom connectors

- В `claude.ai` кастомные интеграции подключаются как `custom connectors` через `remote MCP`.
- Для `claude.ai` сервер должен быть доступен по публичному HTTP(S); локальный `stdio`-сервер для web-версии Claude не подходит.
- Подключение к нашему MCP-серверу идёт из облачной инфраструктуры Anthropic, а не из браузера пользователя.
- Claude поддерживает интерактивные коннекторы, но для них нужен совместимый `MCP Apps` UI-слой поверх обычного MCP.
- Для UI Claude ожидает стандартные `ui://...`-ресурсы, `text/html;profile=mcp-app`, tool metadata через `_meta.ui.resourceUri`, а данные между host и iframe идут по `postMessage`/JSON-RPC.

## Что не совпадало в текущем проекте

- Проект уже умел работать как MCP HTTP server, но UI-метаданные были в основном `OpenAI Apps SDK`-специфичные:
  - `openai/outputTemplate`
  - `openai/widgetDomain`
  - `openai/widgetCSP`
- Виджет умел вызывать инструменты через `window.openai.callTool`, что хорошо для ChatGPT Apps, но недостаточно для Claude/MCP Apps.
- Инициализация сервера не рекламировала поддержку UI extension `io.modelcontextprotocol/ui`.

## Что уже изменено

- В tool descriptor добавлен совместимый `_meta.ui.resourceUri` и `visibility`.
- В `initialize` server response добавлена реклама UI extension с `text/html;profile=mcp-app`.
- В `resources/list` и `resources/read` добавлен `_meta.ui` с `csp`, `domain` и `prefersBorder`.
- Во frontend-виджет добавлен host bridge для JSON-RPC `postMessage`, чтобы поиск мог работать без `window.openai`.
- Исправлен разбор JSON-RPC envelope, чтобы виджет правильно читал payload из `params`/`result`.

## Что ещё нужно сделать

1. Поднять сервер на публичном HTTPS URL, доступном Claude.
2. Решить стратегию auth:
   - без auth для первого smoke test, или
   - OAuth для production connector.
3. Проверить реальный sandbox Claude и при необходимости доработать:
   - theme/hostContext,
   - fullscreen/inline UX,
   - resource domain policy.
4. Протестировать добавление коннектора в `claude.ai` через `Customize > Connectors`.
5. Подготовить deployment notes и env-переменные для production.

## Полезные ссылки

- Claude Help: custom connectors via remote MCP
  - https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Claude API docs: MCP connector
  - https://platform.claude.com/docs/en/agents-and-tools/mcp-connector
- MCP Apps spec / reference
  - https://apps.extensions.modelcontextprotocol.io/api/
  - https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
