# 📘 Manual Complet de Instalare — EasyPark pe VPS
### De la zero la producție, pas cu pas — pentru utilizatori fără experiență tehnică

---

## 📋 Cuprins

1. [Ce ai nevoie înainte să începi](#1-ce-ai-nevoie-înainte-să-începi)
2. [Conectarea la VPS prima dată](#2-conectarea-la-vps-prima-dată)
3. [Actualizarea sistemului](#3-actualizarea-sistemului)
4. [Crearea unui utilizator sigur](#4-crearea-unui-utilizator-sigur)
5. [Securizarea SSH](#5-securizarea-ssh)
6. [Configurarea Firewall-ului](#6-configurarea-firewall-ului)
7. [Instalarea Fail2Ban (protecție anti-hack)](#7-instalarea-fail2ban-protecție-anti-hack)
8. [Instalarea dependențelor aplicației](#8-instalarea-dependențelor-aplicației)
9. [Descărcarea proiectului din GitHub](#9-descărcarea-proiectului-din-github)
10. [Configurarea aplicației](#10-configurarea-aplicației)
11. [Inițializarea bazei de date](#11-inițializarea-bazei-de-date)
12. [Pornirea aplicației cu Systemd](#12-pornirea-aplicației-cu-systemd)
13. [Configurarea Nginx (proxy web)](#13-configurarea-nginx-proxy-web)
14. [Certificat SSL gratuit (HTTPS)](#14-certificat-ssl-gratuit-https)
15. [Verificare finală](#15-verificare-finală)
16. [Comenzi utile zilnice](#16-comenzi-utile-zilnice)
17. [Rezolvarea problemelor frecvente](#17-rezolvarea-problemelor-frecvente)

---

## 1. Ce ai nevoie înainte să începi

### 1.1 Un VPS (server virtual)
Recomandăm unul din furnizorii următori (cel mai ieftin plan e suficient):
- **Hetzner** — https://www.hetzner.com (cel mai ieftin, recomandat)
- **Contabo** — https://contabo.com
- **DigitalOcean** — https://www.digitalocean.com

**Specificații minime recomandate:**
- 1 CPU, 2 GB RAM, 20 GB SSD
- Sistem de operare: **Ubuntu 22.04 LTS** (alege asta la creare)

### 1.2 Un domeniu (opțional, dar recomandat)
Cumpără un domeniu de pe: namecheap.com, godaddy.com, sau porkbun.com  
Exemplu: `easypark-ro.com`

### 1.3 Un program SSH pe calculatorul tău
- **Windows**: descarcă [PuTTY](https://www.putty.org) sau folosește Windows Terminal
- **Mac/Linux**: terminalul implicit funcționează direct

---

## 2. Conectarea la VPS prima dată

Când ai cumpărat VPS-ul, furnizorul îți trimite prin email:
- **Adresa IP** a serverului (ex: `207.180.245.29`)
- **Parola root** (sau o cheie SSH)

### Pe Windows (Terminal / PuTTY):
```
ssh root@ADRESA_IP_A_SERVERULUI
```
Exemplu:
```
ssh root@207.180.245.29
```

### Pe Mac/Linux:
Deschide **Terminal** (Cmd+Space → "Terminal") și scrie:
```bash
ssh root@207.180.245.29
```

Când te întreabă `Are you sure you want to continue connecting?` → scrie **yes** și apasă Enter.  
Introdu parola primită prin email.

> ✅ Dacă apare un prompt de genul `root@server:~#` — ai intrat cu succes!

---

## 3. Actualizarea sistemului

**Copiază și lipește exact aceste comenzi** (una câte una, apasă Enter după fiecare):

```bash
apt update
```
```bash
apt upgrade -y
```
```bash
apt autoremove -y
```

> ⏳ Poate dura 2-5 minute. Asteaptă să se termine fiecare comandă.

---

## 4. Crearea unui utilizator sigur

Nu e recomandat să lucrezi permanent ca `root`. Creăm un utilizator separat:

```bash
adduser easypark
```
Te va întreba o parolă — alege una puternică și **noteaz-o undeva**.  
La celelalte întrebări (Full Name etc.) apasă Enter pentru a sări.

Acordă-i drepturi de administrator:
```bash
usermod -aG sudo easypark
```

---

## 5. Securizarea SSH

### 5.1 Generarea cheii SSH pe calculatorul TĂU (nu pe server)

Deschide un terminal NOU pe calculatorul tău (nu pe server) și rulează:

**Mac/Linux:**
```bash
ssh-keygen -t ed25519 -C "easypark-vps" -f ~/.ssh/easypark_vps
```

**Windows (Terminal):**
```powershell
ssh-keygen -t ed25519 -C "easypark-vps" -f "$env:USERPROFILE\.ssh\easypark_vps"
```

Apasă Enter de două ori (fără parolă pe cheie, sau adaugă una dacă vrei mai multă securitate).

### 5.2 Copierea cheii pe server

**Mac/Linux:**
```bash
ssh-copy-id -i ~/.ssh/easypark_vps.pub root@207.180.245.29
```

**Windows** — rulează asta în terminal:
```powershell
type "$env:USERPROFILE\.ssh\easypark_vps.pub" | ssh root@207.180.245.29 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### 5.3 Testează că funcționează cheia

Într-un terminal NOU pe calculatorul tău:
```bash
ssh -i ~/.ssh/easypark_vps root@207.180.245.29
```
Dacă intri **fără să ceară parola** — cheia funcționează!

### 5.4 Dezactivează autentificarea cu parolă (securitate maximă)

Acum pe server, editează configurația SSH:
```bash
nano /etc/ssh/sshd_config
```

Caută liniile de mai jos și modifică-le exact așa (folosește Ctrl+W pentru căutare în nano):
```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

Salvează: **Ctrl+O** → Enter → **Ctrl+X**

Repornește SSH:
```bash
systemctl restart sshd
```

> ⚠️ **IMPORTANT**: Nu închide sesiunea curentă! Deschide un terminal NOU și testează că poți intra cu cheia înainte de a închide pe cel vechi.

---

## 6. Configurarea Firewall-ului

Instalează și configurează UFW (firewall simplu):

```bash
apt install ufw -y
```

Permite conexiunile necesare:
```bash
ufw allow OpenSSH
ufw allow 80
ufw allow 443
```

Activează firewall-ul:
```bash
ufw enable
```

Când întreabă `Command may disrupt existing ssh connections. Proceed with operation (y|n)?` → scrie **y**

Verifică statusul:
```bash
ufw status
```

Trebuie să vezi ceva de genul:
```
Status: active
To                         Action      From
--                         ------      ----
OpenSSH                    ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
```

---

## 7. Instalarea Fail2Ban (protecție anti-hack)

Fail2Ban blochează automat IP-urile care încearcă să ghicească parola:

```bash
apt install fail2ban -y
```
```bash
systemctl enable fail2ban
systemctl start fail2ban
```

Verifică că rulează:
```bash
systemctl status fail2ban
```
Trebuie să scrie `active (running)` în verde.

---

## 8. Instalarea dependențelor aplicației

```bash
apt install python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx -y
```

> ⏳ Poate dura 3-5 minute.

---

## 9. Descărcarea proiectului din GitHub

### 9.1 Crează directorul aplicației

```bash
mkdir -p /var/www/easypark
cd /var/www/easypark
```

### 9.2 Clonează proiectul

```bash
git clone https://github.com/UTILIZATOR/REPO_PROIECT.git .
```

> 📝 Înlocuiește `UTILIZATOR/REPO_PROIECT` cu adresa exactă a repository-ului GitHub.  
> Dacă repo-ul e privat, vei avea nevoie de un **Personal Access Token** de la GitHub.

**Pentru repo privat:**
```bash
git clone https://TOKENUL_TAU@github.com/UTILIZATOR/REPO_PROIECT.git .
```

### 9.3 Crează mediul virtual Python

```bash
python3 -m venv venv
```

Activează-l:
```bash
source venv/bin/activate
```

Instalează dependențele proiectului:
```bash
pip install -r requirements.txt
```

---

## 10. Configurarea aplicației

### 10.1 Crează fișierul de configurare

```bash
nano /var/www/easypark/.env
```

Completează cu datele tale (înlocuiește valorile dintre `"`):
```env
SECRET_KEY="pune-aici-un-sir-lung-de-caractere-aleatorii-minim-32"
DATABASE_URL="sqlite:///parking.db"
ADMIN_PASSWORD="parola-ta-puternica-pentru-admin"
```

> 🔑 Pentru `SECRET_KEY` poți genera unul sigur cu:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```
> Copiază rezultatul și pune-l în `.env`.

Salvează: **Ctrl+O** → Enter → **Ctrl+X**

### 10.2 Setează permisiunile corecte

```bash
chmod 600 /var/www/easypark/.env
chown -R www-data:www-data /var/www/easypark
chmod -R 755 /var/www/easypark
```

---

## 11. Inițializarea bazei de date

```bash
cd /var/www/easypark
source venv/bin/activate
python3 -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all(); print('DB OK')"
```

Trebuie să apară `DB OK` la final.

---

## 12. Pornirea aplicației cu Systemd

Systemd asigură că aplicația pornește automat după un restart al serverului.

### 12.1 Crează fișierul de serviciu

```bash
nano /etc/systemd/system/easypark.service
```

Lipește exact textul de mai jos:
```ini
[Unit]
Description=EasyPark Flask Application
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/easypark
Environment="PATH=/var/www/easypark/venv/bin"
EnvironmentFile=/var/www/easypark/.env
ExecStart=/var/www/easypark/venv/bin/gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    "app:create_app()"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Salvează: **Ctrl+O** → Enter → **Ctrl+X**

### 12.2 Pornește serviciul

```bash
systemctl daemon-reload
systemctl enable easypark
systemctl start easypark
```

### 12.3 Verifică că rulează

```bash
systemctl status easypark
```

Trebuie să apară `active (running)` în verde.

---

## 13. Configurarea Nginx (proxy web)

Nginx primește cererile din internet și le transmite aplicației.

### 13.1 Crează configurația site-ului

```bash
nano /etc/nginx/sites-available/easypark
```

Lipește exact textul următor (înlocuiește `domeniul-tau.com` cu domeniul tău real):
```nginx
server {
    listen 80;
    server_name domeniul-tau.com www.domeniul-tau.com;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120;
        proxy_connect_timeout 120;
    }

    location /static {
        alias /var/www/easypark/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Salvează: **Ctrl+O** → Enter → **Ctrl+X**

### 13.2 Activează site-ul

```bash
ln -s /etc/nginx/sites-available/easypark /etc/nginx/sites-enabled/
```

Șterge configurația default:
```bash
rm -f /etc/nginx/sites-enabled/default
```

Testează că nu sunt erori de sintaxă:
```bash
nginx -t
```

Trebuie să apară: `syntax is ok` și `test is successful`

Repornește Nginx:
```bash
systemctl restart nginx
```

> ✅ Acum poți accesa aplicația la `http://domeniul-tau.com`

---

## 14. Certificat SSL gratuit (HTTPS)

### 14.1 Asigură-te că domeniul e îndreptat spre serverul tău

Mergi la panoul domeniului tău și adaugă un **A Record**:
```
Tip:   A
Nume:  @ (sau domeniul gol)
Valoare: ADRESA_IP_VPS
TTL:   Auto
```

Și dacă vrei și `www`:
```
Tip:   A
Nume:  www
Valoare: ADRESA_IP_VPS
TTL:   Auto
```

> ⏳ Modificările DNS pot dura între 5 minute și 24 ore să se propage.

### 14.2 Obține certificatul SSL

```bash
certbot --nginx -d domeniul-tau.com -d www.domeniul-tau.com
```

- Introdu adresa ta de **email** când cere
- Acceptă termenii: **A**
- La întrebarea despre redirecționare HTTP→HTTPS alege **2** (Redirect)

### 14.3 Reînnoire automată

Certbot se reînoiește automat. Testează că funcționează:
```bash
certbot renew --dry-run
```

> ✅ Acum aplicația e accesibilă la `https://domeniul-tau.com` cu lacăt verde!

---

## 15. Verificare finală

Rulează pe rând și verifică că totul e verde:

```bash
systemctl status easypark
```
```bash
systemctl status nginx
```
```bash
systemctl status fail2ban
```
```bash
ufw status
```

Testează aplicația în browser:
- `https://domeniul-tau.com` — trebuie să se încarce pagina principală
- `https://domeniul-tau.com/admin` — panoul de administrare

---

## 16. Comenzi utile zilnice

### Actualizarea aplicației (când ai schimbări noi pe GitHub)

```bash
cd /var/www/easypark
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
systemctl restart easypark
```

### Vizualizarea log-urilor în timp real

```bash
journalctl -u easypark -f
```

Ieși cu **Ctrl+C**.

### Repornirea aplicației

```bash
systemctl restart easypark
```

### Repornirea Nginx

```bash
systemctl restart nginx
```

### Vizualizarea ultimelor erori

```bash
journalctl -u easypark -n 50 --no-pager
```

### Backup baza de date

```bash
cp /var/www/easypark/parking.db /root/backup_parking_$(date +%Y%m%d).db
```

### Verificarea spațiului pe disc

```bash
df -h
```

### Verificarea memoriei RAM

```bash
free -h
```

---

## 17. Rezolvarea problemelor frecvente

### ❌ "502 Bad Gateway" în browser

Aplicația nu rulează. Verifică:
```bash
systemctl status easypark
journalctl -u easypark -n 30 --no-pager
```

Cel mai des e o eroare în Python. Citește mesajul de eroare și caută online.

**Încearcă restart:**
```bash
systemctl restart easypark
```

---

### ❌ "Connection refused" la SSH

Probabil ai greșit adresa IP sau portul. Verifică:
```bash
ssh -i ~/.ssh/easypark_vps -p 22 root@ADRESA_IP
```

---

### ❌ Site-ul nu se încarcă deloc (timeout)

Verifică firewall-ul:
```bash
ufw status
ufw allow 80
ufw allow 443
```

Verifică Nginx:
```bash
systemctl status nginx
nginx -t
```

---

### ❌ Certificatul SSL nu se poate obține

Asigură-te că:
1. Domeniul e îndreptat spre IP-ul serverului (verifică cu https://dnschecker.org)
2. Portul 80 e deschis în firewall
3. Nginx rulează pe portul 80

---

### ❌ Aplicația pornește dar dă erori 500

Cel mai des e o problemă cu baza de date sau cu `.env`. Verifică:
```bash
cd /var/www/easypark
source venv/bin/activate
python3 -c "from app import create_app; app = create_app(); print('OK')"
```

---

## 📞 Sumar rapid — de reținut

| Ce vrei să faci | Comanda |
|---|---|
| Intru pe server | `ssh -i ~/.ssh/easypark_vps root@IP` |
| Restart aplicație | `systemctl restart easypark` |
| Actualizez codul | `cd /var/www/easypark && git pull && systemctl restart easypark` |
| Văd erorile | `journalctl -u easypark -n 50 --no-pager` |
| Backup DB | `cp /var/www/easypark/parking.db /root/backup_$(date +%Y%m%d).db` |
| Status general | `systemctl status easypark nginx` |

---

*Manual creat pentru proiectul EasyPark — versiune VPS Ubuntu 22.04*
