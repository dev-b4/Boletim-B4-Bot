import os
import smtplib
import imaplib
import email
from email.message import EmailMessage
import requests
import feedparser
from bs4 import BeautifulSoup
import openai
from datetime import datetime
import pytz
import holidays
import asyncio
from playwright.async_api import async_playwright
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from jinja2 import Template

# Configurações de API e Email
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
EMAIL_USER = os.environ.get('EMAIL_USER', 'ia@b4.capital')
EMAIL_PASS = os.environ.get('EMAIL_PASS', 'AUvJDbe!rWJt@m!F')
EMAIL_TO = 'mkt@b4.capital'
SMTP_SERVER = 'mail.b4.capital'
SMTP_PORT = 465

openai.api_key = OPENAI_API_KEY
ASSETS = ['B4TRII', 'BFTIII', 'ARCIBA', 'APNKAA', 'DWM', 'OWBN']

def is_holiday_or_weekend():
    sp_tz = pytz.timezone('America/Sao_Paulo')
    today = datetime.now(sp_tz).date()
    if today.weekday() >= 5:
        return True
    br_holidays = holidays.Brazil()
    if today in br_holidays:
        return True
    return False

def get_carbon_news():
    # Pega notícia via Google News RSS
    rss_url = "https://news.google.com/rss/search?q=%22cr%C3%A9dito+de+carbono%22+OR+%22mercado+de+carbono%22+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    feed = feedparser.parse(rss_url)
    if not feed.entries:
        return None, None
    entry = feed.entries[0]
    return entry.title, entry.link

def generate_summary(news_link):
    # Tenta extrair o texto para não alucinar
    try:
        r = requests.get(news_link, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        ps = soup.find_all('p')
        raw_text = " ".join([p.get_text() for p in ps[:10] if len(p.get_text()) > 40])
    except:
        raw_text = ""
        
    prompt = f"Faça um resumo profissional e conciso (em 1 parágrafo jornalístico) desta notícia sobre o mercado de carbono. Se não houver texto suficiente, baseie-se no link ou faça um panorama atual.\nNotícia: {raw_text[:2000]}"
    
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    news_text = resp.choices[0].message.content.strip()
    
    t_prompt = f"Crie um título de até 12 palavras para essa notícia: {news_text}"
    t_resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": t_prompt}],
        temperature=0.2
    )
    news_title = t_resp.choices[0].message.content.strip().replace('"', '')
    return news_title, news_text

async def build_pdf(date_str, news_text, news_link, dollar_hoje, bcb_var, indices_data):
    # Gráfico
    prices = []
    variations_text = []
    for ticker_name in ASSETS:
        try:
            item = next(a for a in indices_data['data'] if a['currency'] == ticker_name)
            val = float(item['amount'])
            var_val = indices_data['variations'][ticker_name]
        except:
            val = 100.0
            var_val = bcb_var
        prices.append(val)
        v_dir = '↑' if var_val >= 0 else '↓'
        variations_text.append(f"{v_dir}{abs(var_val):.4f}%")

    plt.figure(figsize=(10, 6))
    bars = plt.bar(ASSETS, prices, color='#7b52ff', width=0.4)
    plt.title('Cotação Diária de Fechamento', fontsize=18, color='#555')
    plt.ylabel('R$', fontsize=12, color='#555')
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#ccc')
    ax.spines['bottom'].set_color('#ccc')
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: format(int(x), ',').replace(',', '.')))
    max_price = max(prices) if prices else 100
    plt.ylim(0, max_price * 1.25)
    for bar, var_txt in zip(bars, variations_text):
        yval = bar.get_height()
        formatted_val = f"{yval:.4f}".replace('.', ',')
        label_text = formatted_val + "\n" + var_txt
        plt.text(bar.get_x() + bar.get_width()/2, yval + (max_price*0.02), label_text, ha='center', va='bottom', fontsize=9, color='#333')

    chart_path = os.path.abspath('chart_draft.png')
    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
    plt.close()

    # PDF
    with open('template.html', 'r', encoding='utf-8') as f:
        template_str = f.read()
    asset_list = [{"name": n, "link": f"https://polygonscan.com/token/{n}"} for n in ASSETS]
    bg_path = os.path.abspath('bg.png')
    template = Template(template_str)
    
    dir_var = '↑' if bcb_var >= 0 else '↓'
    p1 = f"O dólar encerrou o dia cotado a R$ {dollar_hoje:.4f}, apresentando uma volatilidade de {dir_var}{abs(bcb_var):.4f}% em relação ao fechamento anterior. Os ativos de Crédito de Carbono listados na B4, Bolsa de Ação Climática, acompanharam a variação do dia."
    
    html_content = template.render(
        date=date_str,
        news_text=f"{p1}<br><br>{news_text}",
        news_link=news_link,
        chart_path=f"file://{chart_path}",
        bg_path=f"file://{bg_path}",
        assets=asset_list
    )
    html_path = os.path.abspath('rendered_draft.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    pdf_filename = "draft.pdf"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox', '--disable-setuid-sandbox'])
        page = await browser.new_page()
        await page.goto(f"file://{html_path}", wait_until='networkidle')
        await page.pdf(path=pdf_filename, format='A4', print_background=True)
        await browser.close()
    return pdf_filename

def main():
    if is_holiday_or_weekend():
        print("Fim de semana ou feriado. Não roda.")
        return

    sp_tz = pytz.timezone('America/Sao_Paulo')
    today_str = datetime.now(sp_tz).strftime("%d/%m/%Y")
    
    # Já postou hoje?
    WP_URL = 'https://b4.capital/pt/wp-json/wp/v2/posts'
    try:
        r = requests.get(f"{WP_URL}?categories=21&per_page=1", timeout=10)
        posts = r.json()
        if posts and today_str.replace('/', '-') in posts[0]['title']['rendered']:
            print("Já existe post de hoje.")
            return
    except:
        pass

    # Pega dados
    try:
        indices_data = requests.get(f"https://indices.b4.capital/api/quotations?assets={','.join(ASSETS)}").json()
        bcb_var = indices_data['bcbData']['variation']
        dollar_hoje = indices_data['bcbData']['current']
    except:
        dollar_hoje = 5.0
        bcb_var = 0.0

    _, link = get_carbon_news()
    if not link:
        link = "https://b4.capital"
    
    title, text = generate_summary(link)
    
    pdf_file = asyncio.run(build_pdf(today_str, text, link, dollar_hoje, bcb_var, indices_data))
    
    # Enviar E-mail
    msg = EmailMessage()
    msg['Subject'] = f"APROVAÇÃO Boletim B4 - {today_str}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_TO
    
    body = f"""Olá,

Segue a prévia do boletim de hoje ({today_str}).
Se estiver tudo certo, responda a este e-mail com a palavra "OK" para aprovar a postagem.

=========================
[DADOS DO BOT - NÃO APAGUE]
TITULO_BOT: {title}
TEXTO_BOT: {text}
URL_BOT: {link}
=========================
"""
    msg.set_content(body)
    
    with open(pdf_file, 'rb') as f:
        msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename=f"Boletim_{today_str.replace('/','-')}.pdf")
        
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print("E-mail de aprovação enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar email: {e}")

if __name__ == '__main__':
    main()
