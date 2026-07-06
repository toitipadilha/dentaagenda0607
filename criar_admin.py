"""
Cria a sua conta de administrador (dono do sistema).

Rode UMA VEZ na pasta do projeto, no servidor, passando os dados como
variáveis de ambiente (assim nenhuma credencial fica escrita no arquivo,
seguro mesmo que esse .py acabe indo pro Git por engano):

    ADMIN_EMAIL="seu@email.com" ADMIN_SENHA="sua-senha-forte" ADMIN_NOME="José" python3 criar_admin.py

Depois de rodar com sucesso, pode apagar este arquivo se quiser (não é
necessário pro funcionamento do site, é só uma ferramenta de setup).
"""

import os
import getpass

EMAIL = os.environ.get('ADMIN_EMAIL')
SENHA = os.environ.get('ADMIN_SENHA')
NOME  = os.environ.get('ADMIN_NOME', 'Admin')

# se não passou por variável de ambiente, pergunta interativamente
# (getpass não mostra a senha na tela nem fica salva no histórico do bash)
if not EMAIL:
    EMAIL = input('Seu e-mail de login: ').strip()
if not SENHA:
    SENHA = getpass.getpass('Sua senha (não aparece na tela): ').strip()

if not EMAIL or not SENHA:
    print('E-mail e senha são obrigatórios. Abortando.')
    raise SystemExit(1)

from app import app, db, Usuario, Clinica, ADMIN_CLINICA_SLUG

with app.app_context():
    db.create_all()

    if Usuario.query.filter_by(email=EMAIL).first():
        print(f'Já existe um usuário com o e-mail {EMAIL}. Nada foi criado.')
    else:
        clinica_admin = Clinica.query.filter_by(slug=ADMIN_CLINICA_SLUG).first()
        if not clinica_admin:
            clinica_admin = Clinica(nome='Administração do Sistema', slug=ADMIN_CLINICA_SLUG)
            db.session.add(clinica_admin)
            db.session.flush()

        admin = Usuario(
            clinica_id=clinica_admin.id,
            nome=NOME,
            email=EMAIL,
            perfil='admin',
            is_admin=True
        )
        admin.set_senha(SENHA)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin criado! Faça login em /login com {EMAIL}')
