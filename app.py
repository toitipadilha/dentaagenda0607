import os
import json
from datetime import datetime, date, timedelta
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, abort, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///dentaagenda.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12MB — cobre fotos e radiografias do prontuário

db      = SQLAlchemy(app)
bcrypt  = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para continuar.'

# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class Clinica(db.Model):
    __tablename__ = 'clinicas'
    id        = db.Column(db.Integer, primary_key=True)
    nome      = db.Column(db.String(120), nullable=False)
    slug      = db.Column(db.String(60), unique=True, nullable=False)  # ex: dra-ana-lima
    telefone  = db.Column(db.String(20))
    cor_primaria = db.Column(db.String(7), default='#2A7D6F')  # cor da marca da clínica (hex)
    msg_whatsapp = db.Column(db.Text)
    msg_retorno  = db.Column(db.Text)
    msg_aniversario = db.Column(db.Text)
    msg_cobranca = db.Column(db.Text)
    imagem_aniversario = db.Column(db.String(255))  # caminho dentro de static/, ex: uploads/aniversario/clinica_3.jpg
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    usuarios  = db.relationship('Usuario', backref='clinica', lazy=True)
    pacientes = db.relationship('Paciente', backref='clinica', lazy=True)
    consultas = db.relationship('Consulta', backref='clinica', lazy=True)
    horarios  = db.relationship('HorarioBloqueado', backref='clinica', lazy=True)
    lancamentos = db.relationship('Lancamento', backref='clinica', lazy=True)


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id         = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    nome       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    perfil     = db.Column(db.String(20), default='dentista')  # dentista | recepcao
    is_admin   = db.Column(db.Boolean, default=False)          # dono do sistema (você) — vê todas as clínicas
    ultimo_login = db.Column(db.DateTime)

    def set_senha(self, senha):
        self.senha_hash = bcrypt.generate_password_hash(senha).decode('utf-8')

    def check_senha(self, senha):
        return bcrypt.check_password_hash(self.senha_hash, senha)


class Paciente(db.Model):
    __tablename__ = 'pacientes'
    id         = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    nome       = db.Column(db.String(120), nullable=False)
    telefone   = db.Column(db.String(20))
    nascimento = db.Column(db.Date)
    obs        = db.Column(db.Text)
    tag        = db.Column(db.String(20))         # 'vip' | 'hof' | 'atencao' | None
    odontograma = db.Column(db.Text)               # JSON: {"11": "cariado", ...}
    anamnese_token = db.Column(db.String(32), unique=True)  # link público de preenchimento
    criado_em  = db.Column(db.DateTime, default=datetime.utcnow)
    consultas  = db.relationship('Consulta', backref='paciente', lazy=True)
    evolucoes  = db.relationship('Evolucao', backref='paciente', lazy=True,
                                  order_by=lambda: Evolucao.data.desc(), cascade='all, delete-orphan')
    anamneses  = db.relationship('Anamnese', backref='paciente', lazy=True,
                                  order_by=lambda: Anamnese.criado_em.desc(), cascade='all, delete-orphan')


class Evolucao(db.Model):
    __tablename__ = 'evolucoes'
    id           = db.Column(db.Integer, primary_key=True)
    clinica_id   = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    paciente_id  = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    consulta_id  = db.Column(db.Integer, db.ForeignKey('consultas.id'), nullable=True)
    data         = db.Column(db.Date, nullable=False)
    texto        = db.Column(db.Text, nullable=False)
    anexo_arquivo = db.Column(db.String(255))  # caminho dentro de static/, ex: uploads/prontuario/12/abcd.jpg
    anexo_tipo    = db.Column(db.String(10))   # 'imagem' | 'pdf'
    criado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)


class Consulta(db.Model):
    __tablename__ = 'consultas'
    id           = db.Column(db.Integer, primary_key=True)
    clinica_id   = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    paciente_id  = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    data         = db.Column(db.Date, nullable=False)
    hora         = db.Column(db.String(5), nullable=False)   # "09:00"
    procedimento = db.Column(db.String(120))
    status       = db.Column(db.String(20), default='pendente')  # pendente | confirmado | em_atendimento | finalizado | cancelado
    obs          = db.Column(db.Text)
    valor        = db.Column(db.Numeric(10, 2), default=0)
    pago         = db.Column(db.Boolean, default=False)
    criado_em    = db.Column(db.DateTime, default=datetime.utcnow)


class Tarefa(db.Model):
    __tablename__ = 'tarefas'
    id          = db.Column(db.Integer, primary_key=True)
    clinica_id  = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=True)
    titulo      = db.Column(db.String(150), nullable=False)
    descricao   = db.Column(db.Text)
    prazo       = db.Column(db.Date)
    concluida   = db.Column(db.Boolean, default=False)
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)
    paciente    = db.relationship('Paciente')


ANAMNESE_PERGUNTAS = [
    ('queixa', 'Qual sua queixa principal?'),
    ('pressao_alta', 'Tem pressão alta?'),
    ('alergia', 'Possui alguma alergia (medicamento, látex, etc)?'),
    ('hemorragia', 'Já teve alguma hemorragia ou sangramento difícil de estancar?'),
    ('diabetes', 'Tem diabetes?'),
    ('cardiaco', 'Possui algum problema cardíaco?'),
    ('gestante', 'Está grávida ou amamentando?'),
    ('medicamento', 'Faz uso contínuo de algum medicamento? Qual?'),
    ('cirurgia', 'Já passou por alguma cirurgia? Qual?'),
]

class Anamnese(db.Model):
    __tablename__ = 'anamneses'
    id          = db.Column(db.Integer, primary_key=True)
    clinica_id  = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    respostas   = db.Column(db.Text, nullable=False)  # JSON {"queixa": "...", ...}
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)


class HorarioBloqueado(db.Model):
    __tablename__ = 'horarios_bloqueados'
    id         = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    data       = db.Column(db.Date, nullable=False)
    hora       = db.Column(db.String(5), nullable=False)
    motivo     = db.Column(db.String(100))


class Lancamento(db.Model):
    __tablename__ = 'lancamentos'
    id              = db.Column(db.Integer, primary_key=True)
    clinica_id      = db.Column(db.Integer, db.ForeignKey('clinicas.id'), nullable=False)
    tipo            = db.Column(db.String(10), nullable=False)   # receita | despesa
    descricao       = db.Column(db.String(150), nullable=False)
    categoria       = db.Column(db.String(60))
    valor           = db.Column(db.Numeric(10, 2), nullable=False)
    data            = db.Column(db.Date, nullable=False)
    forma_pagamento = db.Column(db.String(30))
    obs             = db.Column(db.Text)
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

HORARIOS = [
    '07:00','07:30','08:00','08:30','09:00','09:30',
    '10:00','10:30','11:00','11:30',
    '13:00','13:30','14:00','14:30','15:00','15:30',
    '16:00','16:30','17:00','17:30','18:00','18:30','19:00'
]

DIAS_SEMANA = ['Seg','Ter','Qua','Qui','Sex','Sáb']
ADMIN_CLINICA_SLUG = '_admin-sistema'  # clínica interna "fantasma" que só existe pra amarrar contas de admin (dono do SaaS)

def get_semana(offset=0):
    """Retorna lista de dates (seg a sáb) da semana com offset."""
    hoje = date.today()
    dow  = hoje.weekday()  # 0=seg
    inicio = hoje - timedelta(days=dow) + timedelta(weeks=offset)
    return [inicio + timedelta(days=i) for i in range(6)]

COR_PADRAO = '2A7D6F'  # teal padrão do sistema, usado quando a clínica não personalizou

def cores_clinica(hex_cor):
    """A partir de UMA cor escolhida pela clínica, calcula as variações usadas
    na interface: tom escuro (hover/destaque), tom claro (fundos suaves) e a
    cor de texto (branco ou escuro) que fica legível em cima da cor principal."""
    hex_cor = (hex_cor or '').strip().lstrip('#')
    if len(hex_cor) != 6 or not all(ch in '0123456789abcdefABCDEF' for ch in hex_cor):
        hex_cor = COR_PADRAO
    r, g, b = int(hex_cor[0:2], 16), int(hex_cor[2:4], 16), int(hex_cor[4:6], 16)

    def mix(canal, alvo, quantidade):
        return round(canal + (alvo - canal) * quantidade)

    escura = (mix(r, 0, 0.30), mix(g, 0, 0.30), mix(b, 0, 0.30))
    clara  = (mix(r, 255, 0.86), mix(g, 255, 0.86), mix(b, 255, 0.86))
    luminancia = 0.299 * r + 0.587 * g + 0.114 * b
    texto = '#FFFFFF' if luminancia < 150 else '#1A1A1A'

    def to_hex(t):
        return '#%02X%02X%02X' % t

    return {
        'primaria': f'#{hex_cor.upper()}',
        'escura': to_hex(escura),
        'clara': to_hex(clara),
        'texto': texto
    }

app.jinja_env.globals['cores_clinica'] = cores_clinica
app.jinja_env.filters['from_json'] = json.loads

def parse_valor(raw):
    if not raw:
        return 0
    raw = raw.strip().replace('R$', '').replace(' ', '')
    if ',' in raw and '.' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    try:
        return round(float(raw), 2)
    except ValueError:
        return 0

def wa_link(telefone, mensagem):
    n = ''.join(filter(str.isdigit, telefone))
    if not n.startswith('55'):
        n = '55' + n
    from urllib.parse import quote
    return f'https://wa.me/{n}?text={quote(mensagem)}'

def build_wa_msg(paciente, consulta):
    from sqlalchemy.orm import object_session
    clinica = consulta.clinica
    template = (clinica.msg_whatsapp or
        'Ola {nome}! Lembrando sua consulta no dia {data} as {hora}. Procedimento: {procedimento}. Ate la!')
    d = consulta.data.strftime('%d/%m/%Y')
    msg = template.replace('{nome}', paciente.nome.split()[0])
    msg = msg.replace('{data}', d)
    msg = msg.replace('{hora}', consulta.hora)
    msg = msg.replace('{procedimento}', consulta.procedimento or '')
    return msg

def build_wa_retorno(paciente, clinica):
    template = (clinica.msg_retorno or
        'Ola {nome}! Faz um tempo que voce nao aparece por aqui. Que tal agendar seu retorno? Estamos com horarios disponiveis essa semana!')
    return template.replace('{nome}', paciente.nome.split()[0])

def build_wa_aniversario(paciente, clinica):
    template = (clinica.msg_aniversario or
        'Feliz aniversario, {nome}! 🎉 Toda a equipe deseja um dia maravilhoso e muita saude pra voce!')
    return template.replace('{nome}', paciente.nome.split()[0])

def build_wa_cobranca(paciente, valor_total, clinica):
    template = (clinica.msg_cobranca or
        'Ola {nome}! Tudo bem? Notamos uma pendencia de R$ {valor} referente ao seu atendimento. Podemos combinar a forma de pagamento?')
    valor_fmt = f'{valor_total:.2f}'.replace('.', ',')
    return template.replace('{nome}', paciente.nome.split()[0]).replace('{valor}', valor_fmt)


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard') if current_user.is_admin else url_for('agenda'))
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        senha = request.form.get('senha','')
        user  = Usuario.query.filter_by(email=email).first()
        if user and user.check_senha(senha):
            login_user(user, remember=True)
            user.ultimo_login = datetime.utcnow()
            db.session.commit()
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('agenda'))
        flash('E-mail ou senha incorretos.', 'erro')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ─────────────────────────────────────────────
# AGENDA
# ─────────────────────────────────────────────

@app.route('/')
@login_required
def agenda():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('agenda_semana'))

@app.route('/agenda')
@login_required
def agenda_semana():
    offset = int(request.args.get('offset', 0))
    dias   = get_semana(offset)
    cid    = current_user.clinica_id

    consultas = Consulta.query.filter(
        Consulta.clinica_id == cid,
        Consulta.data >= dias[0],
        Consulta.data <= dias[-1]
    ).all()

    bloqueados = HorarioBloqueado.query.filter(
        HorarioBloqueado.clinica_id == cid,
        HorarioBloqueado.data >= dias[0],
        HorarioBloqueado.data <= dias[-1]
    ).all()

    # mapa: (data_str, hora) → consulta
    mapa = {}
    for c in consultas:
        mapa[(c.data.isoformat(), c.hora)] = c

    bloq_set = set()
    for b in bloqueados:
        bloq_set.add((b.data.isoformat(), b.hora))

    # avisos do dia: consultas pendentes de confirmação hoje + aniversariantes hoje
    hoje = date.today()
    pendentes_hoje_lista = Consulta.query.filter(
        Consulta.clinica_id == cid, Consulta.data == hoje, Consulta.status == 'pendente'
    ).order_by(Consulta.hora).all()

    aniversariantes_hoje_lista = []
    for p in Paciente.query.filter(Paciente.clinica_id == cid, Paciente.nascimento.isnot(None)).all():
        if p.nascimento.month == hoje.month and p.nascimento.day == hoje.day:
            idade = hoje.year - p.nascimento.year
            aniversariantes_hoje_lista.append((p, idade))
    aniversariantes_hoje_lista.sort(key=lambda t: t[0].nome)

    amanha = hoje + timedelta(days=1)
    amanha_pendentes_lista = Consulta.query.filter(
        Consulta.clinica_id == cid, Consulta.data == amanha, Consulta.status == 'pendente'
    ).order_by(Consulta.hora).all()

    return render_template('agenda.html',
        dias=dias, horarios=HORARIOS, mapa=mapa, bloq_set=bloq_set,
        offset=offset, dias_label=DIAS_SEMANA, hoje=hoje,
        pendentes_hoje=pendentes_hoje_lista, aniversariantes_hoje=aniversariantes_hoje_lista,
        amanha_pendentes=amanha_pendentes_lista, amanha=amanha,
        wa_link=wa_link, build_wa_msg=build_wa_msg, build_wa_aniversario=build_wa_aniversario,
        clinica=current_user.clinica
    )


# ─────────────────────────────────────────────
# CONSULTAS
# ─────────────────────────────────────────────

@app.route('/consultas')
@login_required
def consultas():
    cid  = current_user.clinica_id
    data_filtro = request.args.get('data')
    status_filtro = request.args.get('status')
    q = Consulta.query.filter_by(clinica_id=cid)
    if data_filtro:
        try:
            q = q.filter(Consulta.data == date.fromisoformat(data_filtro))
        except ValueError:
            pass
    if status_filtro:
        q = q.filter(Consulta.status == status_filtro)
    lista = q.order_by(Consulta.data, Consulta.hora).all()
    pacientes = Paciente.query.filter_by(clinica_id=cid).order_by(Paciente.nome).all()
    return render_template('consultas.html', consultas=lista, pacientes=pacientes,
                           data_filtro=data_filtro, status_filtro=status_filtro,
                           wa_link=wa_link, build_wa_msg=build_wa_msg)

@app.route('/consultas/nova', methods=['POST'])
@login_required
def nova_consulta():
    cid = current_user.clinica_id
    pac_id = request.form.get('paciente_id')
    data_str = request.form.get('data')
    hora     = request.form.get('hora')
    if not (pac_id and data_str and hora):
        flash('Preencha paciente, data e horário.', 'erro')
        return redirect(request.referrer or url_for('agenda_semana'))
    c = Consulta(
        clinica_id   = cid,
        paciente_id  = int(pac_id),
        data         = date.fromisoformat(data_str),
        hora         = hora,
        procedimento = request.form.get('procedimento','').strip(),
        status       = request.form.get('status','pendente'),
        obs          = request.form.get('obs','').strip(),
        valor        = parse_valor(request.form.get('valor','')),
        pago         = request.form.get('pago') == 'on'
    )
    db.session.add(c)
    db.session.commit()
    flash('Consulta agendada!', 'ok')
    return redirect(request.referrer or url_for('agenda_semana'))

@app.route('/consultas/<int:cid_>/editar', methods=['POST'])
@login_required
def editar_consulta(cid_):
    c = Consulta.query.filter_by(id=cid_, clinica_id=current_user.clinica_id).first_or_404()
    c.paciente_id  = int(request.form.get('paciente_id', c.paciente_id))
    c.data         = date.fromisoformat(request.form.get('data', c.data.isoformat()))
    c.hora         = request.form.get('hora', c.hora)
    c.procedimento = request.form.get('procedimento','').strip()
    c.status       = request.form.get('status', c.status)
    c.obs          = request.form.get('obs','').strip()
    if 'valor' in request.form:
        c.valor    = parse_valor(request.form.get('valor',''))
    c.pago         = request.form.get('pago') == 'on'
    db.session.commit()
    flash('Consulta atualizada!', 'ok')
    return redirect(request.referrer or url_for('agenda_semana'))

@app.route('/consultas/<int:cid_>/excluir', methods=['POST'])
@login_required
def excluir_consulta(cid_):
    c = Consulta.query.filter_by(id=cid_, clinica_id=current_user.clinica_id).first_or_404()
    Evolucao.query.filter_by(consulta_id=cid_).update({'consulta_id': None})
    db.session.delete(c)
    db.session.commit()
    flash('Consulta excluída.', 'ok')
    return redirect(request.referrer or url_for('agenda_semana'))

@app.route('/consultas/<int:cid_>/status', methods=['POST'])
@login_required
def mudar_status(cid_):
    c = Consulta.query.filter_by(id=cid_, clinica_id=current_user.clinica_id).first_or_404()
    c.status = request.form.get('status', c.status)
    db.session.commit()
    return jsonify({'ok': True, 'status': c.status})

# API para modal de detalhe
@app.route('/api/consulta/<int:cid_>')
@login_required
def api_consulta(cid_):
    c = Consulta.query.filter_by(id=cid_, clinica_id=current_user.clinica_id).first_or_404()
    p = c.paciente
    wa = ''
    if p.telefone:
        wa = wa_link(p.telefone, build_wa_msg(p, c))
    return jsonify({
        'id': c.id,
        'paciente': p.nome,
        'paciente_id': p.id,
        'telefone': p.telefone or '',
        'data': c.data.isoformat(),
        'hora': c.hora,
        'procedimento': c.procedimento or '',
        'status': c.status,
        'obs': c.obs or '',
        'valor': float(c.valor or 0),
        'pago': bool(c.pago),
        'wa_link': wa
    })


# ─────────────────────────────────────────────
# PACIENTES
# ─────────────────────────────────────────────

@app.route('/pacientes')
@login_required
def pacientes():
    cid  = current_user.clinica_id
    q    = request.args.get('q','').strip()
    aba  = request.args.get('aba', 'todos')  # todos | parados | aniversario | inadimplentes

    if aba == 'inadimplentes':
        q_devedores = db.session.query(
            Paciente, db.func.sum(Consulta.valor).label('total_devido')
        ).join(Consulta, Consulta.paciente_id == Paciente.id).filter(
            Paciente.clinica_id == cid,
            Consulta.clinica_id == cid,
            Consulta.pago == False,
            Consulta.valor > 0,
            Consulta.status != 'cancelado'
        ).group_by(Paciente.id)
        if q:
            q_devedores = q_devedores.filter(Paciente.nome.ilike(f'%{q}%'))
        devedores = q_devedores.order_by(db.func.sum(Consulta.valor).desc()).all()
        return render_template('pacientes.html', aba=aba, q=q, devedores=devedores,
                               wa_link=wa_link, build_wa_cobranca=build_wa_cobranca,
                               clinica=current_user.clinica)

    if aba == 'aniversario':
        hoje = date.today()
        todos_q = Paciente.query.filter(Paciente.clinica_id == cid, Paciente.nascimento.isnot(None))
        if q:
            todos_q = todos_q.filter(Paciente.nome.ilike(f'%{q}%'))
        aniversariantes = []
        for p in todos_q.all():
            if p.nascimento.month == hoje.month and p.nascimento.day == hoje.day:
                idade = hoje.year - p.nascimento.year
                aniversariantes.append((p, idade))
        aniversariantes.sort(key=lambda t: t[0].nome)
        return render_template('pacientes.html', aba=aba, q=q,
                               aniversariantes=aniversariantes, wa_link=wa_link,
                               build_wa_aniversario=build_wa_aniversario,
                               clinica=current_user.clinica, hoje=hoje)

    if aba == 'parados':
        dias_limite = int(request.args.get('dias', 90))
        limite = date.today() - timedelta(days=dias_limite)

        # última consulta finalizada (não cancelada) de cada paciente
        ultima_sq = db.session.query(
            Consulta.paciente_id,
            db.func.max(Consulta.data).label('ultima_data')
        ).filter(
            Consulta.clinica_id == cid,
            Consulta.status != 'cancelado'
        ).group_by(Consulta.paciente_id).subquery()

        pacientes_com_consulta = db.session.query(Paciente, ultima_sq.c.ultima_data).join(
            ultima_sq, Paciente.id == ultima_sq.c.paciente_id
        ).filter(
            Paciente.clinica_id == cid,
            ultima_sq.c.ultima_data < limite
        )
        if q:
            pacientes_com_consulta = pacientes_com_consulta.filter(Paciente.nome.ilike(f'%{q}%'))

        parados = [(p, (date.today() - ultima).days) for p, ultima in pacientes_com_consulta.all()]

        # pacientes cadastrados que nunca tiveram consulta
        sub_com_consulta = db.session.query(Consulta.paciente_id).filter(Consulta.clinica_id == cid).subquery()
        nunca_vieram_q = Paciente.query.filter(
            Paciente.clinica_id == cid,
            ~Paciente.id.in_(db.session.query(sub_com_consulta.c.paciente_id))
        )
        if q:
            nunca_vieram_q = nunca_vieram_q.filter(Paciente.nome.ilike(f'%{q}%'))
        for p in nunca_vieram_q.all():
            dias = (date.today() - p.criado_em.date()).days
            if dias >= dias_limite:
                parados.append((p, dias))

        parados.sort(key=lambda t: t[1], reverse=True)
        return render_template('pacientes.html', aba=aba, q=q, dias_limite=dias_limite,
                               parados=parados, wa_link=wa_link, build_wa_retorno=build_wa_retorno,
                               clinica=current_user.clinica)

    lista = Paciente.query.filter_by(clinica_id=cid)
    if q:
        lista = lista.filter(Paciente.nome.ilike(f'%{q}%'))
    lista = lista.order_by(Paciente.nome).all()
    return render_template('pacientes.html', aba=aba, pacientes=lista, q=q, wa_link=wa_link)

@app.route('/pacientes/novo', methods=['POST'])
@login_required
def novo_paciente():
    cid  = current_user.clinica_id
    nome = request.form.get('nome','').strip()
    if not nome:
        flash('Informe o nome do paciente.', 'erro')
        return redirect(url_for('pacientes'))
    nasc_str = request.form.get('nascimento','')
    nasc = date.fromisoformat(nasc_str) if nasc_str else None
    p = Paciente(
        clinica_id = cid,
        nome       = nome,
        telefone   = request.form.get('telefone','').strip(),
        nascimento = nasc,
        obs        = request.form.get('obs','').strip(),
        tag        = request.form.get('tag','').strip() or None
    )
    db.session.add(p)
    db.session.commit()
    flash('Paciente cadastrado!', 'ok')
    return redirect(url_for('pacientes'))

@app.route('/pacientes/<int:pid>/editar', methods=['POST'])
@login_required
def editar_paciente(pid):
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    p.nome     = request.form.get('nome', p.nome).strip()
    p.telefone = request.form.get('telefone','').strip()
    nasc_str   = request.form.get('nascimento','')
    p.nascimento = date.fromisoformat(nasc_str) if nasc_str else None
    p.obs      = request.form.get('obs','').strip()
    p.tag      = request.form.get('tag','').strip() or None
    db.session.commit()
    flash('Paciente atualizado!', 'ok')
    return redirect(url_for('pacientes'))

@app.route('/pacientes/<int:pid>/excluir', methods=['POST'])
@login_required
def excluir_paciente(pid):
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    Tarefa.query.filter_by(paciente_id=pid).update({'paciente_id': None})
    db.session.delete(p)
    db.session.commit()
    flash('Paciente excluído.', 'ok')
    return redirect(url_for('pacientes'))

@app.route('/api/paciente/<int:pid>')
@login_required
def api_paciente(pid):
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    return jsonify({
        'id': p.id, 'nome': p.nome, 'telefone': p.telefone or '',
        'nascimento': p.nascimento.isoformat() if p.nascimento else '',
        'obs': p.obs or '', 'tag': p.tag or ''
    })


# ─────────────────────────────────────────────
# PRONTUÁRIO DIGITAL (histórico clínico do paciente)
# ─────────────────────────────────────────────

EXT_IMAGEM = {'jpg', 'jpeg', 'png', 'webp'}
EXT_PERMITIDAS = EXT_IMAGEM | {'pdf'}

@app.route('/pacientes/<int:pid>/prontuario')
@login_required
def prontuario(pid):
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    consultas_paciente = Consulta.query.filter_by(
        paciente_id=pid, clinica_id=current_user.clinica_id
    ).order_by(Consulta.data.desc()).all()
    odonto_dados = json.loads(p.odontograma) if p.odontograma else {}
    anamnese_url = url_for('anamnese_publica', token=p.anamnese_token, _external=True) if p.anamnese_token else None
    return render_template('prontuario.html', paciente=p, consultas=consultas_paciente, hoje=date.today(),
                           dentes=DENTES_ADULTO, odonto_dados=odonto_dados,
                           anamnese_url=anamnese_url, anamnese_perguntas=ANAMNESE_PERGUNTAS)

@app.route('/pacientes/<int:pid>/evolucoes/nova', methods=['POST'])
@login_required
def nova_evolucao(pid):
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    texto = request.form.get('texto', '').strip()
    if not texto:
        flash('Escreva alguma anotação antes de salvar.', 'erro')
        return redirect(url_for('prontuario', pid=pid))

    data_str = request.form.get('data', '')
    consulta_id = request.form.get('consulta_id') or None

    ev = Evolucao(
        clinica_id=current_user.clinica_id,
        paciente_id=pid,
        consulta_id=int(consulta_id) if consulta_id else None,
        data=date.fromisoformat(data_str) if data_str else date.today(),
        texto=texto,
        criado_por_id=current_user.id
    )

    arquivo = request.files.get('anexo')
    if arquivo and arquivo.filename:
        ext = arquivo.filename.rsplit('.', 1)[-1].lower()
        if ext in EXT_PERMITIDAS:
            pasta = os.path.join(app.root_path, 'static', 'uploads', 'prontuario', str(pid))
            os.makedirs(pasta, exist_ok=True)
            import uuid
            nome_arquivo = f'{uuid.uuid4().hex[:12]}.{ext}'
            arquivo.save(os.path.join(pasta, nome_arquivo))
            ev.anexo_arquivo = f'uploads/prontuario/{pid}/{nome_arquivo}'
            ev.anexo_tipo = 'imagem' if ext in EXT_IMAGEM else 'pdf'
        else:
            flash('Anexo em formato inválido. Use JPG, PNG, WEBP ou PDF.', 'erro')

    db.session.add(ev)
    db.session.commit()
    flash('Evolução adicionada ao prontuário!', 'ok')
    return redirect(url_for('prontuario', pid=pid))

@app.route('/evolucoes/<int:eid>/excluir', methods=['POST'])
@login_required
def excluir_evolucao(eid):
    ev = Evolucao.query.filter_by(id=eid, clinica_id=current_user.clinica_id).first_or_404()
    pid = ev.paciente_id
    if ev.anexo_arquivo:
        caminho = os.path.join(app.root_path, 'static', ev.anexo_arquivo)
        if os.path.exists(caminho):
            os.remove(caminho)
    db.session.delete(ev)
    db.session.commit()
    flash('Evolução excluída.', 'ok')
    return redirect(url_for('prontuario', pid=pid))


# ─────────────────────────────────────────────
# GESTÃO DE TAREFAS
# ─────────────────────────────────────────────

@app.route('/tarefas')
@login_required
def tarefas():
    cid = current_user.clinica_id
    filtro = request.args.get('filtro', 'pendentes')  # pendentes | concluidas | todas
    q = Tarefa.query.filter_by(clinica_id=cid)
    if filtro == 'pendentes':
        q = q.filter_by(concluida=False)
    elif filtro == 'concluidas':
        q = q.filter_by(concluida=True)
    lista = q.order_by(Tarefa.concluida, Tarefa.prazo.is_(None), Tarefa.prazo).all()
    pacientes_lista = Paciente.query.filter_by(clinica_id=cid).order_by(Paciente.nome).all()
    hoje = date.today()
    return render_template('tarefas.html', tarefas=lista, filtro=filtro,
                           pacientes=pacientes_lista, hoje=hoje)

@app.route('/tarefas/nova', methods=['POST'])
@login_required
def nova_tarefa():
    titulo = request.form.get('titulo', '').strip()
    if not titulo:
        flash('Escreva um título pra tarefa.', 'erro')
        return redirect(url_for('tarefas'))
    prazo_str = request.form.get('prazo', '')
    paciente_id = request.form.get('paciente_id') or None
    t = Tarefa(
        clinica_id=current_user.clinica_id,
        titulo=titulo,
        descricao=request.form.get('descricao', '').strip(),
        prazo=date.fromisoformat(prazo_str) if prazo_str else None,
        paciente_id=int(paciente_id) if paciente_id else None
    )
    db.session.add(t)
    db.session.commit()
    flash('Tarefa adicionada!', 'ok')
    return redirect(url_for('tarefas'))

@app.route('/tarefas/<int:tid>/concluir', methods=['POST'])
@login_required
def concluir_tarefa(tid):
    t = Tarefa.query.filter_by(id=tid, clinica_id=current_user.clinica_id).first_or_404()
    t.concluida = not t.concluida
    db.session.commit()
    return jsonify({'ok': True, 'concluida': t.concluida})

@app.route('/tarefas/<int:tid>/excluir', methods=['POST'])
@login_required
def excluir_tarefa(tid):
    t = Tarefa.query.filter_by(id=tid, clinica_id=current_user.clinica_id).first_or_404()
    db.session.delete(t)
    db.session.commit()
    flash('Tarefa excluída.', 'ok')
    return redirect(url_for('tarefas'))


# ─────────────────────────────────────────────
# ANAMNESE DIGITAL
# ─────────────────────────────────────────────

@app.route('/pacientes/<int:pid>/anamnese/gerar-link', methods=['POST'])
@login_required
def gerar_link_anamnese(pid):
    import secrets
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    if not p.anamnese_token:
        p.anamnese_token = secrets.token_urlsafe(16)
        db.session.commit()
    flash('Link de anamnese gerado! Copie e envie pro paciente.', 'ok')
    return redirect(url_for('prontuario', pid=pid))

@app.route('/anamnese/<token>', methods=['GET', 'POST'])
def anamnese_publica(token):
    p = Paciente.query.filter_by(anamnese_token=token).first_or_404()
    if request.method == 'POST':
        respostas = {chave: request.form.get(chave, '').strip() for chave, _ in ANAMNESE_PERGUNTAS}
        a = Anamnese(clinica_id=p.clinica_id, paciente_id=p.id, respostas=json.dumps(respostas, ensure_ascii=False))
        db.session.add(a)
        db.session.commit()
        return render_template('anamnese_publica.html', paciente=p, enviado=True, perguntas=ANAMNESE_PERGUNTAS)
    return render_template('anamnese_publica.html', paciente=p, enviado=False, perguntas=ANAMNESE_PERGUNTAS)


# ─────────────────────────────────────────────
# ODONTOGRAMA
# ─────────────────────────────────────────────

DENTES_ADULTO = [18,17,16,15,14,13,12,11, 21,22,23,24,25,26,27,28,
                 48,47,46,45,44,43,42,41, 31,32,33,34,35,36,37,38]

@app.route('/pacientes/<int:pid>/odontograma/salvar', methods=['POST'])
@login_required
def salvar_odontograma(pid):
    p = Paciente.query.filter_by(id=pid, clinica_id=current_user.clinica_id).first_or_404()
    dados = request.get_json(silent=True) or {}
    p.odontograma = json.dumps(dados, ensure_ascii=False)
    db.session.commit()
    return jsonify({'ok': True})


# ─────────────────────────────────────────────
# TELA TV
# ─────────────────────────────────────────────

@app.route('/tv/<slug>')
def tv(slug):
    clinica = Clinica.query.filter_by(slug=slug).first_or_404()
    hoje    = date.today()
    consultas = Consulta.query.filter_by(clinica_id=clinica.id, data=hoje)\
        .filter(Consulta.status != 'cancelado')\
        .order_by(Consulta.hora).all()
    return render_template('tv.html', clinica=clinica, consultas=consultas, hoje=hoje)

@app.route('/api/tv/<slug>')
def api_tv(slug):
    clinica = Clinica.query.filter_by(slug=slug).first_or_404()
    hoje    = date.today()
    consultas = Consulta.query.filter_by(clinica_id=clinica.id, data=hoje)\
        .filter(Consulta.status != 'cancelado')\
        .order_by(Consulta.hora).all()
    return jsonify([{
        'nome': c.paciente.nome.split()[0] + ' ' + c.paciente.nome.split()[-1] if len(c.paciente.nome.split()) > 1 else c.paciente.nome,
        'hora': c.hora,
        'status': c.status
    } for c in consultas])


# ─────────────────────────────────────────────
# SETUP INICIAL (criar clínica + usuário admin)
# ─────────────────────────────────────────────

@app.route('/setup', methods=['GET','POST'])
def setup():
    if Clinica.query.count() > 0:
        return redirect(url_for('login'))
    if request.method == 'POST':
        clinica = Clinica(
            nome     = request.form['nome_clinica'].strip(),
            slug     = request.form['slug'].strip().lower().replace(' ','-'),
            telefone = request.form.get('telefone','').strip()
        )
        db.session.add(clinica)
        db.session.flush()
        user = Usuario(
            clinica_id = clinica.id,
            nome       = request.form['nome_usuario'].strip(),
            email      = request.form['email'].strip().lower(),
            perfil     = 'dentista'
        )
        user.set_senha(request.form['senha'])
        db.session.add(user)
        db.session.commit()
        flash('Sistema configurado! Faça login.', 'ok')
        return redirect(url_for('login'))
    return render_template('setup.html')


# ─────────────────────────────────────────────
# INIT DB
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────

@app.route('/configuracoes', methods=['GET','POST'])
@login_required
def configuracoes():
    clinica = current_user.clinica
    if request.method == 'POST':
        clinica.msg_whatsapp = request.form.get('msg_whatsapp', '').strip()
        clinica.msg_retorno  = request.form.get('msg_retorno', '').strip()
        clinica.msg_aniversario = request.form.get('msg_aniversario', '').strip()
        clinica.msg_cobranca = request.form.get('msg_cobranca', '').strip()
        cor = request.form.get('cor_primaria', '').strip()
        if cor and len(cor) == 7 and cor.startswith('#'):
            clinica.cor_primaria = cor

        if request.form.get('remover_imagem_aniversario') == 'on' and clinica.imagem_aniversario:
            caminho_antigo = os.path.join(app.root_path, 'static', clinica.imagem_aniversario)
            if os.path.exists(caminho_antigo):
                os.remove(caminho_antigo)
            clinica.imagem_aniversario = None

        arquivo = request.files.get('imagem_aniversario')
        if arquivo and arquivo.filename:
            ext = arquivo.filename.rsplit('.', 1)[-1].lower()
            if ext in ('jpg', 'jpeg', 'png', 'webp'):
                pasta = os.path.join(app.root_path, 'static', 'uploads', 'aniversario')
                os.makedirs(pasta, exist_ok=True)
                nome_arquivo = f'clinica_{clinica.id}.{ext}'
                arquivo.save(os.path.join(pasta, nome_arquivo))
                clinica.imagem_aniversario = f'uploads/aniversario/{nome_arquivo}'
            else:
                flash('Imagem em formato inválido. Use JPG, PNG ou WEBP.', 'erro')

        db.session.commit()
        flash('Configuracoes salvas!', 'ok')
        return redirect(url_for('configuracoes'))
    return render_template('configuracoes.html', clinica=clinica)

@app.route('/configuracoes/senha', methods=['POST'])
@login_required
def trocar_senha():
    atual = request.form.get('senha_atual', '')
    nova = request.form.get('senha_nova', '')
    confirmar = request.form.get('senha_confirmar', '')

    if not current_user.check_senha(atual):
        flash('Senha atual incorreta.', 'erro')
        return redirect(url_for('configuracoes'))
    if len(nova) < 6:
        flash('A nova senha precisa ter pelo menos 6 caracteres.', 'erro')
        return redirect(url_for('configuracoes'))
    if nova != confirmar:
        flash('A confirmação não bateu com a nova senha.', 'erro')
        return redirect(url_for('configuracoes'))

    current_user.set_senha(nova)
    db.session.commit()
    flash('Senha alterada com sucesso!', 'ok')
    return redirect(url_for('configuracoes'))


# ─────────────────────────────────────────────
# FINANCEIRO
# ─────────────────────────────────────────────

CATEGORIAS_DESPESA = ['Aluguel','Material odontológico','Salários','Equipamentos','Laboratório','Marketing','Contas (água/luz/internet)','Impostos','Outros']
CATEGORIAS_RECEITA = ['Consulta/Procedimento','Convênio','Outros']
FORMAS_PAGAMENTO = ['Dinheiro','Pix','Cartão débito','Cartão crédito','Convênio','Boleto/Transferência']

def mes_atual_str():
    return date.today().strftime('%Y-%m')

def parse_mes(mes_str):
    """Retorna (primeiro_dia, ultimo_dia) do mês 'YYYY-MM'."""
    try:
        ano, mes = map(int, mes_str.split('-'))
    except (ValueError, AttributeError):
        hoje = date.today()
        ano, mes = hoje.year, hoje.month
    primeiro = date(ano, mes, 1)
    if mes == 12:
        ultimo = date(ano, 12, 31)
    else:
        ultimo = date(ano, mes + 1, 1) - timedelta(days=1)
    return primeiro, ultimo

@app.route('/financeiro')
@login_required
def financeiro():
    cid = current_user.clinica_id
    mes = request.args.get('mes', mes_atual_str())
    primeiro, ultimo = parse_mes(mes)

    lancamentos = Lancamento.query.filter(
        Lancamento.clinica_id == cid,
        Lancamento.data >= primeiro,
        Lancamento.data <= ultimo
    ).order_by(Lancamento.data.desc()).all()

    consultas_pagas = Consulta.query.filter(
        Consulta.clinica_id == cid,
        Consulta.data >= primeiro,
        Consulta.data <= ultimo,
        Consulta.pago == True,
        Consulta.valor > 0
    ).order_by(Consulta.data.desc()).all()

    consultas_a_receber = Consulta.query.filter(
        Consulta.clinica_id == cid,
        Consulta.data >= primeiro,
        Consulta.data <= ultimo,
        Consulta.pago == False,
        Consulta.valor > 0,
        Consulta.status != 'cancelado'
    ).order_by(Consulta.data).all()

    receita_consultas = sum(float(c.valor or 0) for c in consultas_pagas)
    receita_avulsa     = sum(float(l.valor) for l in lancamentos if l.tipo == 'receita')
    total_receitas      = receita_consultas + receita_avulsa
    total_despesas       = sum(float(l.valor) for l in lancamentos if l.tipo == 'despesa')
    saldo                = total_receitas - total_despesas
    a_receber            = sum(float(c.valor or 0) for c in consultas_a_receber)

    # linha do tempo combinada (lançamentos manuais + consultas pagas), mais recentes primeiro
    itens = []
    for l in lancamentos:
        itens.append({
            'origem': 'lancamento', 'id': l.id, 'tipo': l.tipo, 'data': l.data,
            'descricao': l.descricao, 'categoria': l.categoria or '—',
            'valor': float(l.valor), 'forma_pagamento': l.forma_pagamento or '—'
        })
    for c in consultas_pagas:
        itens.append({
            'origem': 'consulta', 'id': c.id, 'tipo': 'receita', 'data': c.data,
            'descricao': f'{c.paciente.nome} — {c.procedimento or "Consulta"}',
            'categoria': 'Consulta/Procedimento', 'valor': float(c.valor or 0),
            'forma_pagamento': '—'
        })
    itens.sort(key=lambda i: i['data'], reverse=True)

    mes_anterior = (primeiro - timedelta(days=1)).strftime('%Y-%m')
    mes_seguinte = (ultimo + timedelta(days=1)).strftime('%Y-%m')

    return render_template('financeiro.html',
        itens=itens, mes=mes, mes_label=primeiro.strftime('%m/%Y'),
        mes_anterior=mes_anterior, mes_seguinte=mes_seguinte,
        total_receitas=total_receitas, total_despesas=total_despesas,
        saldo=saldo, a_receber=a_receber, qtd_a_receber=len(consultas_a_receber),
        categorias_despesa=CATEGORIAS_DESPESA, categorias_receita=CATEGORIAS_RECEITA,
        formas_pagamento=FORMAS_PAGAMENTO
    )

@app.route('/financeiro/novo', methods=['POST'])
@login_required
def novo_lancamento():
    cid = current_user.clinica_id
    descricao = request.form.get('descricao','').strip()
    valor_raw = request.form.get('valor','')
    data_str  = request.form.get('data','')
    if not (descricao and valor_raw and data_str):
        flash('Preencha descrição, valor e data.', 'erro')
        return redirect(request.referrer or url_for('financeiro'))
    l = Lancamento(
        clinica_id      = cid,
        tipo            = request.form.get('tipo','despesa'),
        descricao       = descricao,
        categoria       = request.form.get('categoria','').strip(),
        valor           = parse_valor(valor_raw),
        data            = date.fromisoformat(data_str),
        forma_pagamento = request.form.get('forma_pagamento','').strip(),
        obs             = request.form.get('obs','').strip()
    )
    db.session.add(l)
    db.session.commit()
    flash('Lançamento adicionado!', 'ok')
    return redirect(url_for('financeiro', mes=data_str[:7]))

@app.route('/financeiro/<int:lid>/editar', methods=['POST'])
@login_required
def editar_lancamento(lid):
    l = Lancamento.query.filter_by(id=lid, clinica_id=current_user.clinica_id).first_or_404()
    l.tipo            = request.form.get('tipo', l.tipo)
    l.descricao       = request.form.get('descricao', l.descricao).strip()
    l.categoria       = request.form.get('categoria','').strip()
    l.valor           = parse_valor(request.form.get('valor', str(l.valor)))
    l.data            = date.fromisoformat(request.form.get('data', l.data.isoformat()))
    l.forma_pagamento = request.form.get('forma_pagamento','').strip()
    l.obs             = request.form.get('obs','').strip()
    db.session.commit()
    flash('Lançamento atualizado!', 'ok')
    return redirect(url_for('financeiro', mes=l.data.strftime('%Y-%m')))

@app.route('/financeiro/<int:lid>/excluir', methods=['POST'])
@login_required
def excluir_lancamento(lid):
    l = Lancamento.query.filter_by(id=lid, clinica_id=current_user.clinica_id).first_or_404()
    mes = l.data.strftime('%Y-%m')
    db.session.delete(l)
    db.session.commit()
    flash('Lançamento excluído.', 'ok')
    return redirect(url_for('financeiro', mes=mes))

@app.route('/api/lancamento/<int:lid>')
@login_required
def api_lancamento(lid):
    l = Lancamento.query.filter_by(id=lid, clinica_id=current_user.clinica_id).first_or_404()
    return jsonify({
        'id': l.id, 'tipo': l.tipo, 'descricao': l.descricao,
        'categoria': l.categoria or '', 'valor': float(l.valor),
        'data': l.data.isoformat(), 'forma_pagamento': l.forma_pagamento or '',
        'obs': l.obs or ''
    })


# ─────────────────────────────────────────────
# ADMIN (painel do dono do sistema — visão de todas as clínicas)
# ─────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_dashboard():
    hoje = date.today()
    primeiro_mes = hoje.replace(day=1)
    q = request.args.get('q','').strip()

    clinicas_q = Clinica.query.filter(Clinica.slug != ADMIN_CLINICA_SLUG)
    if q:
        clinicas_q = clinicas_q.filter(Clinica.nome.ilike(f'%{q}%'))
    clinicas = clinicas_q.order_by(Clinica.criado_em.desc()).all()

    dados = []
    for c in clinicas:
        qtd_pacientes = Paciente.query.filter_by(clinica_id=c.id).count()
        qtd_consultas_mes = Consulta.query.filter(
            Consulta.clinica_id == c.id,
            Consulta.data >= primeiro_mes, Consulta.data <= hoje
        ).count()
        receita_mes = float(db.session.query(db.func.coalesce(db.func.sum(Consulta.valor), 0)).filter(
            Consulta.clinica_id == c.id, Consulta.pago == True,
            Consulta.data >= primeiro_mes, Consulta.data <= hoje
        ).scalar() or 0)
        usuarios = Usuario.query.filter_by(clinica_id=c.id).order_by(Usuario.nome).all()
        logins = [u.ultimo_login for u in usuarios if u.ultimo_login]
        ultimo_acesso = max(logins) if logins else None
        dados.append({
            'clinica': c, 'qtd_pacientes': qtd_pacientes, 'qtd_consultas_mes': qtd_consultas_mes,
            'receita_mes': receita_mes, 'usuarios': usuarios, 'ultimo_acesso': ultimo_acesso
        })

    total_clinicas = len(dados)
    total_pacientes = sum(d['qtd_pacientes'] for d in dados)
    total_receita_mes = sum(d['receita_mes'] for d in dados)

    return render_template('admin_dashboard.html',
        dados=dados, q=q, mes_label=hoje.strftime('%m/%Y'),
        total_clinicas=total_clinicas, total_pacientes=total_pacientes,
        total_receita_mes=total_receita_mes
    )

@app.route('/admin/clinicas/nova', methods=['POST'])
@admin_required
def admin_nova_clinica():
    nome  = request.form.get('nome_clinica','').strip()
    slug  = request.form.get('slug','').strip().lower().replace(' ','-')
    telefone = request.form.get('telefone','').strip()
    nome_usuario = request.form.get('nome_usuario','').strip()
    email = request.form.get('email','').strip().lower()
    senha = request.form.get('senha','')

    if not (nome and slug and nome_usuario and email and senha):
        flash('Preencha todos os campos obrigatórios.', 'erro')
        return redirect(url_for('admin_dashboard'))
    if slug == ADMIN_CLINICA_SLUG or Clinica.query.filter_by(slug=slug).first():
        flash('Esse identificador (slug) já está em uso. Escolha outro.', 'erro')
        return redirect(url_for('admin_dashboard'))
    if Usuario.query.filter_by(email=email).first():
        flash('Já existe um usuário com esse e-mail.', 'erro')
        return redirect(url_for('admin_dashboard'))

    clinica = Clinica(nome=nome, slug=slug, telefone=telefone, cor_primaria=request.form.get('cor_primaria', '').strip() or f'#{COR_PADRAO}')
    db.session.add(clinica)
    db.session.flush()
    user = Usuario(clinica_id=clinica.id, nome=nome_usuario, email=email, perfil='dentista')
    user.set_senha(senha)
    db.session.add(user)
    db.session.commit()
    flash(f'Clínica "{nome}" criada com sucesso!', 'ok')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/clinicas/<int:cid_>/excluir', methods=['POST'])
@admin_required
def admin_excluir_clinica(cid_):
    c = Clinica.query.filter(Clinica.id == cid_, Clinica.slug != ADMIN_CLINICA_SLUG).first_or_404()
    nome = c.nome
    Evolucao.query.filter_by(clinica_id=c.id).delete()
    Anamnese.query.filter_by(clinica_id=c.id).delete()
    Tarefa.query.filter_by(clinica_id=c.id).delete()
    Lancamento.query.filter_by(clinica_id=c.id).delete()
    HorarioBloqueado.query.filter_by(clinica_id=c.id).delete()
    Consulta.query.filter_by(clinica_id=c.id).delete()
    Paciente.query.filter_by(clinica_id=c.id).delete()
    Usuario.query.filter_by(clinica_id=c.id).delete()
    db.session.delete(c)
    db.session.commit()
    flash(f'Clínica "{nome}" e todos os seus dados foram excluídos.', 'ok')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/usuarios/<int:uid>/resetar-senha', methods=['POST'])
@admin_required
def admin_resetar_senha(uid):
    import secrets
    u = Usuario.query.filter(Usuario.id == uid, Usuario.clinica_id != None).first_or_404()
    nova_senha = secrets.token_urlsafe(6)  # ex: "kX9p2Qz"
    u.set_senha(nova_senha)
    db.session.commit()
    flash(f'Senha de {u.nome} ({u.email}) resetada! Nova senha: {nova_senha} — copie agora, ela não vai aparecer de novo.', 'ok')
    return redirect(url_for('admin_dashboard'))


# ─────────────────────────────────────────────
# PWA — ícone e manifest personalizados por clínica
# ─────────────────────────────────────────────

_cache_icones = {}  # cache em memória (por processo) pra não redesenhar o PNG a cada request

def _gerar_icone_png(cor_hex, tamanho, maskable):
    chave = (cor_hex, tamanho, maskable)
    if chave in _cache_icones:
        return _cache_icones[chave]

    from PIL import Image, ImageDraw
    import io

    hex_limpo = (cor_hex or COR_PADRAO).lstrip('#')
    if len(hex_limpo) != 6:
        hex_limpo = COR_PADRAO
    teal = tuple(int(hex_limpo[i:i+2], 16) for i in (0, 2, 4)) + (255,)
    branco = (255, 255, 255, 255)

    img = Image.new('RGBA', (tamanho, tamanho), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, tamanho, tamanho], fill=teal)
        escala = tamanho * 0.34
    else:
        raio = tamanho * 0.22
        d.rounded_rectangle([0, 0, tamanho, tamanho], radius=raio, fill=teal)
        escala = tamanho * 0.40

    cx, cy = tamanho / 2, tamanho / 2
    w, h = escala, escala * 1.15
    d.rounded_rectangle([cx - w*0.5, cy - h*0.55, cx + w*0.5, cy + h*0.05], radius=w*0.5, fill=branco)
    d.polygon([(cx - w*0.30, cy - h*0.05), (cx - w*0.06, cy - h*0.05),
               (cx - w*0.12, cy + h*0.50), (cx - w*0.34, cy + h*0.20)], fill=branco)
    d.polygon([(cx + w*0.30, cy - h*0.05), (cx + w*0.06, cy - h*0.05),
               (cx + w*0.12, cy + h*0.50), (cx + w*0.34, cy + h*0.20)], fill=branco)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    dados = buf.getvalue()
    _cache_icones[chave] = dados
    return dados

@app.route('/icon/<slug>/<int:tamanho>.png')
def icone_clinica(slug, tamanho):
    clinica = Clinica.query.filter_by(slug=slug).first_or_404()
    maskable = request.args.get('maskable') == '1'
    tamanho = max(32, min(tamanho, 512))
    dados = _gerar_icone_png(clinica.cor_primaria, tamanho, maskable)
    return Response(dados, mimetype='image/png')

@app.route('/manifest/<slug>.json')
def manifest_clinica(slug):
    clinica = Clinica.query.filter_by(slug=slug).first_or_404()
    c = cores_clinica(clinica.cor_primaria)
    manifest = {
        'name': clinica.nome,
        'short_name': clinica.nome[:20],
        'description': f'Agenda, financeiro e pacientes — {clinica.nome}',
        'start_url': '/?pwa=1',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'portrait-primary',
        'background_color': '#F9F7F4',
        'theme_color': c['primaria'],
        'lang': 'pt-BR',
        'icons': [
            {'src': url_for('icone_clinica', slug=slug, tamanho=192), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': url_for('icone_clinica', slug=slug, tamanho=512), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': url_for('icone_clinica', slug=slug, tamanho=192) + '?maskable=1', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'maskable'},
            {'src': url_for('icone_clinica', slug=slug, tamanho=512) + '?maskable=1', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ]
    }
    return jsonify(manifest)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False, host='0.0.0.0', port=5003)