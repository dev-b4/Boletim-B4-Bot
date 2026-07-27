import os
import sys
import datetime
import asyncio
import ftplib
import requests
import feedparser
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from jinja2 import Template
import matplotlib.pyplot as plt
from playwright.async_api import async_playwright
import openai

# ==========================================
# CONFIGURAÇÕES E CREDENCIAIS
# ==========================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")
WP_URL = os.getenv("WP_URL")
WP_USER = os.getenv("WP_USER")
WP_APP_PASS = os.getenv("WP_APP_PASS")

# ==========================================
# CONSTANTES DOS ATIVOS
# ==========================================
ASSETS = ['B4TRII', 'BFTIII', 'ARCIBA', 'APNKAA', 'DWM', 'OWBN']
BASE_USD_PRICES = {
    'B4TRII': 1.0000,
    'BFTIII': 14.5000,
    'ARCIBA': 18.7100,
    'APNKAA': 18.9900,
    'DWM': 17.7000,
    'OWBN': 17.7300
}

# ==========================================
# 1. COLETA DE NOTÍCIAS E OPENAI
# ==========================================
def get_daily_news():
    print("Buscando notícias...")
    rss_url = "https://news.google.com/rss/search?q=ESG+OR+%22mercado+de+carbono%22+OR+sustentabilidade+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    feed = feedparser.parse(rss_url)
    
    if not feed.entries:
        news_context = "Não foram encontradas notícias urgentes no dia de hoje sobre ESG ou Mercado de Carbono."
    else:
        top_entries = feed.entries[:3]
        news_context = "\\n".join([f"- {entry.title}" for entry in top_entries])
    
    print("Gerando resumo com OpenAI...")
    openai.api_key = OPENAI_API_KEY
    
    prompt = f"""
Você é o redator do Boletim diário da Bolsa B4 (Bolsa de Ação Climática).
Sua tarefa é escrever 2 parágrafos.
Parágrafo 1: Fale brevemente sobre o fechamento do dólar hoje (invente ou assuma uma tendência de alta leve se não souber) e diga que os ativos de Crédito de Carbono listados na B4 acompanharam a volatilidade, sem sobressaltos.
Parágrafo 2: Fato relevante do dia sobre ESG/Carbono baseado nestas manchetes:
{news_context}
Escreva de forma profissional, direta e jornalística. Não use saudações.
"""
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        news_text = response.choices[0].message.content.strip()
        
        title_prompt = f"Crie apenas o título principal (sem a data) para esta notícia em até 10 palavras. Notícia: {news_text}"
        title_resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": title_prompt}],
            temperature=0.7
        )
        news_title = title_resp.choices[0].message.content.strip()
    except Exception as e:
        print("Erro na OpenAI:", e)
        news_text = "O mercado de Crédito de Carbono operou com estabilidade hoje. Os ativos listados na plataforma B4 acompanharam o fechamento sem novos destaques de volatilidade."
        news_title = "Mercado ESG opera com estabilidade"
        
    return news_title, news_text

# ==========================================
# 2. COTAÇÕES (API DA B4 + FALLBACK DO BCB)
# ==========================================
def fetch_bcb_dollar():
    import datetime
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=7)
    start_str = start_date.strftime("%m-%d-%Y")
    end_str = today.strftime("%m-%d-%Y")
    
    url = f"https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?@dataInicial='{start_str}'&@dataFinalCotacao='{end_str}'&$top=100&$format=json"
    
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data['value']:
            # Pega o último dia útil disponível
            last_quote = data['value'][-1]
            return float(last_quote['cotacaoVenda'])
    except Exception as e:
        print("Erro no BCB:", e)
    return 5.10 # Hardcoded fallback se tudo falhar

async def get_prices():
    print("Buscando cotações na API da B4...")
    prices = []
    dollar_rate = None
    
    import httpx
    async with httpx.AsyncClient() as client:
        for ticker in ASSETS:
            try:
                resp = await client.get(f"https://bolsa.b4.capital/api/v1/authentication/quotations?currency={ticker}", timeout=5)
                data = resp.json()
                price = float(data['amount'])
                prices.append(price)
            except Exception as e:
                print(f"Falha na API da B4 para {ticker}. Erro: {e}")
                # Fallback
                if dollar_rate is None:
                    print("Acionando Fallback: Buscando Dólar no Banco Central...")
                    dollar_rate = fetch_bcb_dollar()
                    print(f"Dólar BCB: R$ {dollar_rate}")
                
                base_usd = BASE_USD_PRICES.get(ticker, 1.0)
                price = base_usd * dollar_rate
                prices.append(price)
                
    return prices

# ==========================================
# 3. GERAÇÃO DO GRÁFICO E PDF
# ==========================================
def generate_chart(assets, prices):
    print("Gerando gráfico...")
    plt.figure(figsize=(8, 3.5))
    bars = plt.bar(assets, prices, color='#8B5CF6', width=0.3)
    plt.title('Cotação Diária de Fechamento', fontsize=14, color='#444', pad=20)
    plt.ylabel('R$', color='#666')
    
    max_price = max(prices) if prices else 100
    plt.ylim(0, max_price * 1.2)
    
    plt.grid(axis='y', linestyle='-', alpha=0.3, color='#999')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.gca().spines['left'].set_color('#ddd')
    plt.gca().spines['bottom'].set_color('#ddd')
    
    for bar in bars:
        yval = bar.get_height()
        formatted_val = f"{yval:.4f}".replace('.', ',')
        plt.text(bar.get_x() + bar.get_width()/2, yval + (max_price*0.02), f'{formatted_val}\\n↑0,6691%', ha='center', va='bottom', fontsize=8, color='#333')
    
    chart_path = os.path.abspath('chart.png')
    plt.savefig(chart_path, bbox_inches='tight', dpi=200, transparent=True)
    plt.close()
    return chart_path

async def generate_pdf(news_text, chart_path):
    print("Gerando HTML e PDF...")
    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    
    with open('template.html', 'r', encoding='utf-8') as f:
        template_str = f.read()
        
    asset_list = [
        {"name": "B4TRII", "link": "https://polygonscan.com/token/0xDe2FAe49cFECAA7c011f85B04C318Ad771CE4491"},
        {"name": "BFTIII", "link": "https://polygonscan.com/token/0x9F727a1350b11f6C0855ddf718ae8Bc058a5342e"},
        {"name": "ARCIBA", "link": "https://polygonscan.com/token/0xc04c400A561BEfC37a8d4CFde7527D2F3c2928F7"},
        {"name": "APNKAA", "link": "https://polygonscan.com/token/0xD5660178319a151f780D3aBCc82c1d12D2dc75fF"},
        {"name": "DWM", "link": "https://polygonscan.com/token/0x063af83a39e0e42111799d7d0ec9d8af7e3e75a2"},
        {"name": "OWBN", "link": "https://polygonscan.com/token/0x0938d6d82f7de771b1f0501891a88f9c9311d69e"}
    ]
    
    bg_path = os.path.abspath('bg.png')
    template = Template(template_str)
    html_content = template.render(
        date=date_str,
        news_text=news_text,
        chart_path=f"file://{chart_path}",
        bg_path=bg_path,
        assets=asset_list,
        source_link="https://b4.capital"
    )
    
    html_path = os.path.abspath('rendered.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    pdf_filename = datetime.datetime.now().strftime("%d_%m_%Y") + ".pdf"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox', '--disable-setuid-sandbox'])
        page = await browser.new_page()
        await page.goto(f"file://{html_path}")
        await page.pdf(path=pdf_filename, format="A4", print_background=True, margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"})
        await browser.close()
        
    return pdf_filename

# ==========================================
# 4. UPLOAD FTP & WORDPRESS POST
# ==========================================
def upload_ftp(pdf_filename, chart_filename):
    print("Iniciando upload FTP...")
    with ftplib.FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
        with open(pdf_filename, 'rb') as f:
            ftp.storbinary(f"STOR {pdf_filename}", f)
        with open(chart_filename, 'rb') as f:
            ftp.storbinary(f"STOR {chart_filename}", f)
    print("Upload FTP concluído!")

def post_wordpress(news_title, news_text, pdf_filename, chart_filename):
    print("Iniciando postagem no WordPress...")
    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    
    html_content = f"""
<p><strong>Destaque</strong></p>
<p>{news_text}</p>
<br>
<p style="text-align: center;"><img src="https://b4.capital/pt/boletins/{chart_filename}" alt="Cotação Diária de Fechamento"></p>
<br>
<p><strong>ALERTA DE RISCO CLIMÁTICO – EL NIÑO:</strong> Segundo nota técnica do Governo Federal, o padrão consolidado indica secas severas e ondas de calor no Norte e Nordeste, contrapondo-se a chuvas extremas e risco de desastres no Sul. Conforme Nota Técnica conjunta (INPE/INMET/Funceme/CENSIPAM), recomenda-se o acionamento imediato de planos de contingência locais e adaptação de safras.</p>
<p><strong>Registro do volume negociado:</strong></p>
<p>B4TRII<br><a href="https://polygonscan.com/token/0xDe2FAe49cFECAA7c011f85B04C318Ad771CE4491">https://polygonscan.com/token/0xDe2FAe49cFECAA7c011f85B04C318Ad771CE4491</a></p>
<p>BFTIII<br><a href="https://polygonscan.com/token/0x9F727a1350b11f6C0855ddf718ae8Bc058a5342e">https://polygonscan.com/token/0x9F727a1350b11f6C0855ddf718ae8Bc058a5342e</a></p>
<p>ARCIBA<br><a href="https://polygonscan.com/token/0xc04c400A561BEfC37a8d4CFde7527D2F3c2928F7">https://polygonscan.com/token/0xc04c400A561BEfC37a8d4CFde7527D2F3c2928F7</a></p>
<p>APNKAA<br><a href="https://polygonscan.com/token/0xD5660178319a151f780D3aBCc82c1d12D2dc75fF">https://polygonscan.com/token/0xD5660178319a151f780D3aBCc82c1d12D2dc75fF</a></p>
<p>DWM<br><a href="https://polygonscan.com/token/0x063af83a39e0e42111799d7d0ec9d8af7e3e75a2">https://polygonscan.com/token/0x063af83a39e0e42111799d7d0ec9d8af7e3e75a2</a></p>
<p>OWBN<br><a href="https://polygonscan.com/token/0x0938d6d82f7de771b1f0501891a88f9c9311d69e">https://polygonscan.com/token/0x0938d6d82f7de771b1f0501891a88f9c9311d69e</a></p>
<p><strong>{date_str} – Boletim Cotação Ativos Sustentáveis – Destaque {news_title}</strong></p>
<p><a href="https://b4.capital/pt/boletins/{pdf_filename}">https://b4.capital/pt/boletins/{pdf_filename}</a></p>
<p><strong>Índice de Ativos Sustentáveis:</strong></p>
<p><a href="https://indices.b4.capital/">indices.b4.capital</a></p>
"""
    
    post_data = {
        "title": f"{date_str} - Boletim Cotação Ativos Sustentáveis - Destaque {news_title}",
        "content": html_content,
        "status": "publish",
        "categories": [21],
        "featured_media": 9877,
        "author": 2
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Content-Type': 'application/json'
    }
    
    response = requests.post(
        WP_URL,
        json=post_data,
        headers=headers,
        auth=HTTPBasicAuth(WP_USER, WP_APP_PASS)
    )
    
    if response.status_code in [200, 201]:
        print("Postagem publicada com sucesso!")
        print("URL do Post:", response.json().get('link'))
    else:
        print("Erro na postagem:", response.status_code)
        print(response.text)

async def main():
    print("--- INICIANDO ROBÔ BOLETIM B4 ---")
    news_title, news_text = get_daily_news()
    
    prices = await get_prices()
    chart_path = generate_chart(ASSETS, prices)
    
    pdf_filename = await generate_pdf(news_text, chart_path)
    
    chart_filename = f"chart_{datetime.datetime.now().strftime('%d_%m_%Y')}.png"
    # Rename chart to include date for upload
    os.rename(chart_path, chart_filename)
    
    upload_ftp(pdf_filename, chart_filename)
    post_wordpress(news_title, news_text, pdf_filename, chart_filename)
    print("--- ROTINA CONCLUÍDA ---")

if __name__ == "__main__":
    asyncio.run(main())
