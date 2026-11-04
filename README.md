# Kokiko for Claude

Search the Kokiko cosmetics and personal care catalog in Moldova from Claude.
Browse matching products in interactive cards with names, manufacturers, prices,
images, and links when those details are available in the catalog. Open a product
page on [kokiko.md](https://www.kokiko.md/) to continue shopping and complete a
purchase on the store website.

## Connect to Claude

1. Open Claude's **Customize > Connectors** section.
2. Select **Add > Add custom connector**.
3. Enter **Kokiko** as the name and this remote MCP server URL:

   ```text
   https://kokikoapps.idoctor.md/mcp
   ```

4. Choose **No sign in** and leave request headers empty. Searching the public
   catalog does not require a Kokiko account or an API key.
5. Select **Add**, then enable Kokiko for your conversation.

Access to custom connectors also depends on your Claude account and workspace
settings. See Claude's [custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

## Try these requests

- "Find hand cream at Kokiko."
- "Найди крем для рук в Kokiko."
- "Găsește cremă de mâini în Kokiko."

Use product names or keywords. Search results can be displayed in Russian or
Romanian, using the translations supplied by the catalog. Product cards show
prices in MDL. Check the product page for the latest price and purchasing details.
If a search finds no matching items, try a shorter query or another product name.

## MCP tool reference

The connector exposes one read-only tool, `search_products`.

| Argument | Required | Meaning |
| --- | --- | --- |
| `query` | Yes | Product name or free-text search query. |
| `limit` | No | Maximum number of returned products, as an integer of at least 1. |
| `language` | No | Preferred result language: `ru` or `ro`. |

Example request for an MCP client:

```json
{
  "jsonrpc": "2.0",
  "id": "kokiko-search-ru",
  "method": "tools/call",
  "params": {
    "name": "search_products",
    "arguments": {
      "query": "крем для рук",
      "limit": 5,
      "language": "ru"
    }
  }
}
```

Example with a Romanian query and preferred language:

```json
{
  "jsonrpc": "2.0",
  "id": "kokiko-search-ro",
  "method": "tools/call",
  "params": {
    "name": "search_products",
    "arguments": {
      "query": "cremă de mâini",
      "limit": 5,
      "language": "ro"
    }
  }
}
```

The response includes `structuredContent.products` and `structuredContent.no_results`.
The interactive product cards are served from `ui://widget/products.html` using
the MCP Apps UI extension.

## Support and privacy

- Support: [kokikomoldova@gmail.com](mailto:kokikomoldova@gmail.com).
- Store contact page: [Kokiko contacts](https://www.kokiko.md/ru/contacts).
- Published store privacy policy: [Kokiko privacy policy](https://www.kokiko.md/ru/info/policy).

Send support requests to the address above. Use the search field for product
queries; it does not require contact or payment details.
