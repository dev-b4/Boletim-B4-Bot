import os
import imaplib
import email
from email.header import decode_header
import requests
import re
import ftplib
import pytz
from datetime import datetime
from requests.auth import HTTPBasicAuth
import asyncio
from playwright.async_api import async_playwright
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from jinja2 import Template
import holidays

EMAIL_USER = os.environ.get('EMAIL_USER', 'ia@b4.capital')
EMAIL_PASS = os.environ.get('EMAIL_PASS', 'AUvJDbe!rWJt@m!F')
IMAP_SERVER = 'mail.b4.capital'
IMAP_PORT = 993

FTP_HOST = os.environ.get('FTP_HOST', 'b4.capital')
FTP_USER = os.environ.get('FTP_USER', 'ia@b4.capital')
FTP_PASS = os.environ.get('FTP_PASS', 'cpsess04283890132@#E$@wedf')

WP_URL = os.environ.get('WP_URL', 'https://b4.capital/pt/wp-json/wp/v2/posts')
WP_USER = os.environ.get('WP_USER', 'admin@b4.capital')
WP_APP_PASS = os.environ.get('WP_APP_PASS', 'udew SJEu bxtZ Ss6Y R8QA 17bG')

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

def parse_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get('Content-Disposition'))
            if ctype == 'text/plain' and 'attachment' not in cdispo:
                return part.get_payload(decode=True).decode('utf-8', errors='ignore')
    else:
        return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return ""

async def generate_and_publish(title, text, news_url):
    sp_tz = pytz.timezone('America/Sao_Paulo')
    now = datetime.now(sp_tz)
    date_str = now.strftime("%d/%m/%Y")
    file_date = now.strftime("%d_%m_%Y")
    
    try:
        indices_data = requests.get(f"https://indices.b4.capital/api/quotations?assets={','.join(ASSETS)}").json()
        bcb_var = indices_data['bcbData']['variation']
        dollar_hoje = indices_data['bcbData']['current']
    except:
        dollar_hoje = 5.0
        bcb_var = 0.0

    # PDF & Gráfico
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

    chart_path = os.path.abspath(f'chart_{file_date}.png')
    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
    plt.close()

    with open('template.html', 'r', encoding='utf-8') as f:
        template_str = f.read()
    asset_list = [{"name": n, "link": f"https://polygonscan.com/token/{n}"} for n in ASSETS]
    bg_path = os.path.abspath('bg.png')
    template = Template(template_str)
    dir_var = '↑' if bcb_var >= 0 else '↓'
    p1 = f"O dólar encerrou o dia cotado a R$ {dollar_hoje:.4f}, apresentando uma volatilidade de {dir_var}{abs(bcb_var):.4f}% em relação ao fechamento anterior. Os ativos de Crédito de Carbono listados na B4, Bolsa de Ação Climática, acompanharam a variação do dia."
    
    html_content = template.render(
        date=date_str,
        news_text=f"{p1}<br><br>{text}",
        news_link=news_url,
        chart_path=f"file://{chart_path}",
        bg_path=f"file://{bg_path}",
        assets=asset_list
    )
    html_path = os.path.abspath('rendered_final.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    pdf_filename = f"{file_date}.pdf"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox', '--disable-setuid-sandbox'])
        page = await browser.new_page()
        await page.goto(f"file://{html_path}", wait_until='networkidle')
        await page.pdf(path=pdf_filename, format='A4', print_background=True)
        await browser.close()

    # FTP
    try:
        with ftplib.FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
            with open(pdf_filename, 'rb') as f:
                ftp.storbinary(f"STOR {pdf_filename}", f)
            with open(chart_path, 'rb') as f:
                ftp.storbinary(f"STOR chart_{file_date}.png", f)
        print("FTP OK")
    except Exception as e:
        print("Erro FTP:", e)

    # WP
    news_html = f"<p>{p1}</p>\n<p>{text}</p>"
    post_html = f"""
<p><strong>Destaque</strong></p>
{news_html}

<img src="https://b4.capital/pt/boletins/chart_{file_date}.png" alt="Cotação Diária de Fechamento">
<br>

<br><br>
<p><strong>Fonte de Informação:</strong><br>
<a href="{news_url}" target="_blank">{news_url}</a></p>

<br>
<p><strong>ALERTA DE RISCO CLIMÁTICO – EL NIÑO:</strong> Segundo nota técnica do Governo Federal, o padrão consolidado indica secas severas e ondas de calor no Norte e Nordeste, contrapondo-se a chuvas extremas e risco de desastres no Sul. Conforme Nota Técnica conjunta (INPE/INMET/Funceme/CENSIPAM), recomenda-se o acionamento imediato de planos de contingência locais e adaptação de safras.<br>
<a href="https://www.gov.br/inpe/pt-br/assuntos/ultimas-noticias/nota-tecnica-conjunta-aponta-alta-probabilidade-de-el-nino-no-segundo-semestre-de-2026">https://www.gov.br/inpe/pt-br/assuntos/ultimas-noticias/nota-tecnica-conjunta-aponta-alta-probabilidade-de-el-nino-no-segundo-semestre-de-2026</a></p>

<p><strong>Registro do volume negociado:</strong></p>
<p>B4TRII<br><a href="https://polygonscan.com/token/0xDe2FAe49cFECAA7c011f85B04C318Ad771CE4491">https://polygonscan.com/token/0xDe2FAe49cFECAA7c011f85B04C318Ad771CE4491</a></p>
<p>BFTIII<br><a href="https://polygonscan.com/token/0x9F727a1350b11f6C0855ddf718ae8Bc058a5342e">https://polygonscan.com/token/0x9F727a1350b11f6C0855ddf718ae8Bc058a5342e</a></p>
<p>ARCIBA<br><a href="https://polygonscan.com/token/0xc04c400A561BEfC37a8d4CFde7527D2F3c2928F7">https://polygonscan.com/token/0xc04c400A561BEfC37a8d4CFde7527D2F3c2928F7</a></p>
<p>APNKAA<br><a href="https://polygonscan.com/token/0xD5660178319a151f780D3aBCc82c1d12D2dc75fF">https://polygonscan.com/token/0xD5660178319a151f780D3aBCc82c1d12D2dc75fF</a></p>
<p>DWM<br><a href="https://polygonscan.com/token/0x063af83a39e0e42111799d7d0ec9d8af7e3e75a2">https://polygonscan.com/token/0x063af83a39e0e42111799d7d0ec9d8af7e3e75a2</a></p>
<p>OWBN<br><a href="https://polygonscan.com/token/0x0938d6d82f7de771b1f0501891a88f9c9311d69e">https://polygonscan.com/token/0x0938d6d82f7de771b1f0501891a88f9c9311d69e</a></p>

<p><strong>{date_str} – Boletim Cotação Ativos Sustentáveis – Destaque {title}</strong><br>
<a href="https://b4.capital/pt/boletins/{file_date}.pdf">https://b4.capital/pt/boletins/{file_date}.pdf</a></p>

<p><strong>Índice de Ativos Sustentáveis:</strong><br>
<a href="https://indices.b4.capital">https://indices.b4.capital</a></p>
"""
    post_date = now.replace(hour=17, minute=23, second=0).isoformat()
    post_data = {
        'title': f'{date_str} - Boletim Cotação Ativos Sustentáveis - Destaque {title}',
        'content': post_html,
        'status': 'publish',
        'categories': [21], 
        'author': 2,        
        'featured_media': 9877, 
        'date': post_date
    }
    headers = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}
    response = requests.post(WP_URL, json=post_data, headers=headers, auth=HTTPBasicAuth(WP_USER, WP_APP_PASS))
    if response.status_code == 201:
        print("Postagem aprovada e publicada no WordPress!")
    else:
        print("Erro WP:", response.text)

def main():
    if is_holiday_or_weekend():
        return

    sp_tz = pytz.timezone('America/Sao_Paulo')
    today_str = datetime.now(sp_tz).strftime("%d/%m/%Y")

    # Já postou hoje?
    try:
        r = requests.get(f"{WP_URL}?categories=21&per_page=1", timeout=10)
        posts = r.json()
        if posts and today_str.replace('/', '-') in posts[0]['title']['rendered']:
            print("Já postado hoje.")
            return
    except:
        pass

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select('inbox')
        
        status, messages = mail.search(None, '(UNSEEN)')
        if status != 'OK':
            return
            
        for num in messages[0].split():
            res, msg_data = mail.fetch(num, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg['Subject'])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else 'utf-8')
                    
                    if f"APROVA" in subject and today_str in subject:
                        body = parse_body(msg)
                        
                        # Verifica se o usuario disse OK (ignora o histórico no fim)
                        first_lines = body.lower().split('dados do bot')[0]
                        if 'ok' in first_lines or 'aprovado' in first_lines or 'pode publicar' in first_lines:
                            title_match = re.search(r'TITULO_BOT:\s*(.*)', body)
                            text_match = re.search(r'TEXTO_BOT:\s*(.*)', body)
                            url_match = re.search(r'URL_BOT:\s*(.*)', body)
                            
                            if title_match and text_match and url_match:
                                print("Aprovação recebida! Publicando...")
                                asyncio.run(generate_and_publish(title_match.group(1).strip(), text_match.group(1).strip(), url_match.group(1).strip()))
                                
                                # Marca como lida e arquiva (move para Lixeira ou só deixa lida)
                                mail.store(num, '+FLAGS', '\\Seen')
                                break
        mail.close()
        mail.logout()
    except Exception as e:
        print("Erro IMAP:", e)

if __name__ == '__main__':
    main()
