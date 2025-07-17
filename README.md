# SEC Analyst MCP Server

[](https://opensource.org/licenses/MIT)

An advanced, multi-tool **Model Context Protocol (MCP)** server that connects AI assistants like Claude Desktop to the `sec-api.io` service, enabling deep financial research and analysis of SEC filings.

This server acts as a specialized financial research assistant, giving your AI the ability to look up company identifiers, retrieve annual reports, parse specific sections, track insider trades, analyze institutional ownership, and extract specific financial metrics from XBRL data.

## Features

This MCP server provides a suite of powerful tools for financial analysis:

  * **`find_cik`**: Translates a stock ticker to its official CIK identifier.
  * **`find_cusip`**: Translates a stock ticker to its CUSIP identifier, required for some advanced queries.
  * **`get_latest_annual_filings`**: Fetches metadata for the most recent 10-K filings, including direct links to the HTML and XBRL documents.
  * **`extract_section_from_filing`**: Pulls the full text of a specific section (e.g., "1A - Risk Factors") from a filing URL.
  * **`get_insider_trades`**: Retrieves the latest Form 4 filings to show recent insider buying and selling activity.
  * **`get_institutional_holders`**: Uses Form 13F data to find the top institutional managers holding a particular stock.
  * **`get_executive_compensation`**: Fetches the total compensation for a company's top executives.
  * **`get_financial_metric`**: Extracts specific financial data (like Revenues or Net Income) directly from a filing's XBRL data.
  * **`preload_xbrl_summary`**: Efficiently pre-loads an XBRL file into cache for faster analysis.
  * **`get_financial_snapshot`**: Pulls multiple financial metrics at once from an XBRL file.

## Getting Started

Follow these instructions to get the SEC Analyst MCP Server running on your local machine and connected to your AI assistant.

### Prerequisites

  * Python 3.9+
  * An API key from [sec-api.io](https://sec-api.io) (a free tier is available).

### Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/wanderingspirit03/sec-scraper-mcp
    cd my-sec-scraper
    ```

2.  **Create and activate a virtual environment:**

    ```bash
    # Create the environment
    python3 -m venv .venv

    # Activate it (on macOS/Linux)
    source .venv/bin/activate
    ```

3.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up your API Key:**

      * Create a file named `.env` in the main project folder.
      * Add your API key to this file:
        ```
        SEC_API_IO_KEY=YOUR_API_KEY_HERE
        ```

### Usage: Connecting to Claude Desktop

This server is designed to be run automatically by an MCP client like Claude Desktop.

1.  Find your Claude Desktop `mcp.json` configuration file.

2.  Add the following block to the `mcpServers` object. **Remember to replace `/path/to/your/project/` with the actual full path to the `my-sec-scraper` folder on your computer.**

    ```json
    "sec-analyst-assistant": {
      "displayName": "SEC Analyst Assistant",
      "description": "A custom tool to fetch and analyze financial data from the SEC.",
      "transport": "stdio",
      "command": "/path/to/your/project/my-sec-scraper/.venv/bin/python",
      "args": [
        "/path/to/your/project/my-sec-scraper/server.py"
      ]
    }
    ```

3.  Save the file and restart Claude Desktop. The "SEC Analyst Assistant" will now be available as a tool.

## Example Prompts

Here are some examples of how you can use the tool in Claude.

**Example 1: Quick Insider Check**

> Using my SEC Analyst Assistant, please get the latest insider transactions for the ticker **TSLA**.

**Example 2: Multi-step Financial Analysis**

> **Step 1:** "Using my SEC Analyst Assistant, get the latest annual filings for **NVDA**."
>
> **Step 2:** "Great. Now take the **XBRL URL** from the most recent filing and use the `get_financial_metric` tool to find their **Revenues** and **NetIncomeLoss**."

## License

This project is licensed under the MIT License - see the `LICENSE.md` file for details.

## Acknowledgments

  * This tool is powered by the excellent [sec-api.io](https://sec-api.io) service.
  * Built with the [FastMCP](https://github.com/jlowin/fastmcp) library.

\</immersive\>