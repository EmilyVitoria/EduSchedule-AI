"""EduSchedule AI | projeto acadêmico Flask + SQLite.
Execute com: python app.py
Atenção: demonstração acadêmica compartilhada; use dados fictícios.
"""
import csv
import io
import os
import secrets
import hmac
import math
import random
import sqlite3
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, Response

BASE = Path(__file__).resolve().parent
BANCO = BASE / 'escola.db'
TURMAS = ('1º ano', '2º ano', '3º ano')
DIAS = ('Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta')
HORAS = ('07:00', '08:00', '09:00', '10:00', '11:00')
app = Flask(__name__)
# Configure uma chave estável no ambiente ao hospedar o projeto.
app.secret_key = os.environ.get('EDU_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.environ.get('EDU_HTTPS') == '1')
FUNCOES = ('Professor(a)', 'Coordenação', 'Direção', 'Administrativo', 'Outro')
FUSO = timezone(timedelta(hours=-3))  # Horário de Picos–PI



# Cada operação abre uma conexão com o SQLite. As chaves estrangeiras ajudam a manter os vínculos válidos.
def conectar():
    con = sqlite3.connect(BANCO)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


# Cria as tabelas que ainda não existem; não precisamos apagar o banco para atualizar o sistema.
def iniciar_banco():
    with conectar() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS alunos (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
          turma TEXT NOT NULL, matricula TEXT UNIQUE, ativo INTEGER NOT NULL DEFAULT 1,
          criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS professores (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
          ativo INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS atribuicoes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          professor_id INTEGER NOT NULL REFERENCES professores(id),
          turma TEXT NOT NULL, disciplina TEXT NOT NULL,
          aulas_semana INTEGER NOT NULL CHECK(aulas_semana BETWEEN 1 AND 25),
          UNIQUE(turma, disciplina)
        );
        CREATE TABLE IF NOT EXISTS restricoes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          professor_id INTEGER NOT NULL REFERENCES professores(id),
          dia INTEGER NOT NULL CHECK(dia BETWEEN 0 AND 4),
          horario INTEGER NOT NULL CHECK(horario BETWEEN 0 AND 4),
          UNIQUE(professor_id, dia, horario)
        );
        CREATE TABLE IF NOT EXISTS horarios (
          turma TEXT NOT NULL, dia INTEGER NOT NULL, horario INTEGER NOT NULL,
          atribuicao_id INTEGER NOT NULL REFERENCES atribuicoes(id),
          PRIMARY KEY(turma,dia,horario)
        );
        CREATE TABLE IF NOT EXISTS notas (
          aluno_id INTEGER NOT NULL REFERENCES alunos(id),
          atribuicao_id INTEGER NOT NULL REFERENCES atribuicoes(id),
          bimestre INTEGER NOT NULL CHECK(bimestre BETWEEN 1 AND 4),
          nota REAL NOT NULL CHECK(nota BETWEEN 0 AND 10),
          PRIMARY KEY(aluno_id,atribuicao_id,bimestre)
        );
        CREATE TABLE IF NOT EXISTS chamadas (
          id INTEGER PRIMARY KEY AUTOINCREMENT, dia_aula TEXT NOT NULL,
          turma TEXT NOT NULL, horario INTEGER NOT NULL,
          atribuicao_id INTEGER NOT NULL REFERENCES atribuicoes(id),
          UNIQUE(dia_aula,turma,horario)
         );
        CREATE TABLE IF NOT EXISTS presencas (
          chamada_id INTEGER NOT NULL REFERENCES chamadas(id),
          aluno_id INTEGER NOT NULL REFERENCES alunos(id),
          presente INTEGER NOT NULL CHECK(presente IN (0,1)),
          PRIMARY KEY(chamada_id,aluno_id)
        );
        CREATE TABLE IF NOT EXISTS configuracoes (
          id INTEGER PRIMARY KEY CHECK(id=1),
          media_minima REAL NOT NULL DEFAULT 7,
          frequencia_minima REAL NOT NULL DEFAULT 75,
          semanas_letivas INTEGER NOT NULL DEFAULT 40
        );
        INSERT OR IGNORE INTO configuracoes VALUES (1,7,75,40);
        CREATE TABLE IF NOT EXISTS acessos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nome TEXT NOT NULL, funcao TEXT NOT NULL, acesso_utc TEXT NOT NULL
        );
        ''')


# Padroniza as mensagens de erro que aparecem na interface.
def erro(msg, codigo=400):
    return jsonify({'erro': msg}), codigo


# Lê os dados JSON enviados pelo JavaScript.
def corpo():
    return request.get_json(silent=True) or {}


# Confere os campos antes de gravar, mesmo que o navegador já tenha feito uma validação.
def validar_aluno(dados):
    nome = str(dados.get('nome') or '').strip()
    turma = str(dados.get('turma') or '').strip()
    matricula = str(dados.get('matricula') or '').strip() or None
    if not 2 <= len(nome) <= 120: raise ValueError('Nome deve ter entre 2 e 120 caracteres.')
    if turma not in TURMAS: raise ValueError('Selecione uma turma válida.')
    if matricula and len(matricula) > 30: raise ValueError('Matrícula muito longa.')
    return nome, turma, matricula


# Identificação de participantes: não é verificação de identidade.
# Guarda um código aleatório na sessão para proteger os formulários de entrada e saída.
def token_formulario():
    if 'token_form' not in session:
        session['token_form'] = secrets.token_hex(24)
    return session['token_form']


# Compara o código recebido com o da sessão.
def token_valido():
    token = session.get('token_form')
    return bool(token and hmac.compare_digest(token.encode(), request.form.get('csrf', '').encode()))


# Sem identificação, o visitante não pode consultar nem alterar os dados da demonstração.
@app.before_request
def exigir_identificacao():
    if request.path.startswith('/api/') and not session.get('visitante'):
        return jsonify(erro='Identifique-se para acessar a demonstração.'), 401
    # Alterações são enviadas pelo JavaScript como JSON, não por formulários externos.
    if request.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not request.is_json:
        return jsonify(erro='Envie os dados no formato JSON.'), 415


# Evita que páginas com informações pessoais fiquem guardadas no cache do navegador.
@app.after_request
def proteger_respostas(resposta):
    if request.endpoint != 'static':
        resposta.headers['Cache-Control'] = 'no-store'
    return resposta


# A primeira visita passa pela identificação; depois mostramos o painel normal.
@app.get('/')
def inicio():
    if not session.get('visitante'):
        return redirect(url_for('identificar'))
    return render_template('index.html', modo='sistema', token=token_formulario())


# Só registramos uma entrada após o envio válido do formulário e a ciência do participante.
@app.route('/identificar', methods=['GET', 'POST'])
def identificar():
    if session.get('visitante'):
        return redirect(url_for('inicio'))
    mensagem = ''
    nome = ''
    funcao = ''
    if request.method == 'POST':
        nome = ' '.join(request.form.get('nome', '').split())
        funcao = request.form.get('funcao', '')
        if not token_valido():
            mensagem = 'Sessão expirada. Tente novamente.'
        elif not 2 <= len(nome) <= 120 or funcao not in FUNCOES or request.form.get('ciente') != 'sim':
            mensagem = 'Preencha o nome, a função e confirme a ciência do registro.'
        else:
            agora = datetime.now(timezone.utc).isoformat(timespec='seconds')
            with conectar() as con:
                acesso_id = con.execute('INSERT INTO acessos(nome,funcao,acesso_utc) VALUES(?,?,?)',
                                        (nome, funcao, agora)).lastrowid
            session.clear()
            session['visitante'] = acesso_id
            return redirect(url_for('inicio'))
    return render_template('index.html', modo='identificar', funcoes=FUNCOES,
                           mensagem=mensagem, nome=nome, funcao=funcao, token=token_formulario())


# Encerra a sessão; uma nova entrada será registrada quando a pessoa se identificar novamente.
@app.post('/sair')
def sair():
    if not token_valido():
        return 'Sessão expirada. Atualize a página.', 400
    session.clear()
    return redirect(url_for('identificar'))


# O painel privado usa senha de administração definida fora do código.
def verificar_admin():
    senha = os.environ.get('EDU_ADMIN_PASSWORD', '')
    if len(senha) < 12:
        return Response('Painel desabilitado: configure EDU_ADMIN_PASSWORD com pelo menos 12 caracteres.', 503)
    auth = request.authorization
    if not auth or auth.type != 'basic' or auth.username != 'admin' or not hmac.compare_digest((auth.password or '').encode(), senha.encode()):
        return Response('Acesso reservado à responsável pelo projeto.', 401,
                        {'WWW-Authenticate': 'Basic realm="EduSchedule AI - Administracao", charset="UTF-8"'})
    return None


# O banco guarda o horário em UTC. Para o relatório, convertemos para o horário de Picos.
def registros_acessos():
    with conectar() as con:
        linhas = con.execute('SELECT nome,funcao,acesso_utc FROM acessos ORDER BY id DESC').fetchall()
    return [{'nome': r['nome'], 'funcao': r['funcao'],
             'data': datetime.fromisoformat(r['acesso_utc']).astimezone(FUSO).strftime('%d/%m/%Y'),
             'hora': datetime.fromisoformat(r['acesso_utc']).astimezone(FUSO).strftime('%H:%M:%S')}
            for r in linhas]


# A lista de nomes não faz parte da área pública da demonstração.
@app.get('/admin/acessos')
def admin_acessos():
    bloqueio = verificar_admin()
    if bloqueio is not None:
        return bloqueio
    registros = registros_acessos()
    distintos = len({r['nome'].casefold() for r in registros})
    return render_template('index.html', modo='acessos', registros=registros, distintos=distintos)


def celula_csv(valor):
    # Impede que nomes autodeclarados sejam interpretados como fórmulas.
    return "'" + valor if valor.lstrip().startswith(('=', '+', '-', '@')) else valor


# Gera uma planilha CSV para facilitar a organização das evidências acadêmicas.
@app.get('/admin/acessos/csv')
def exportar_acessos():
    bloqueio = verificar_admin()
    if bloqueio is not None:
        return bloqueio
    arquivo = io.StringIO()
    escritor = csv.writer(arquivo, delimiter=';')
    escritor.writerow(['Nome', 'Função', 'Data', 'Hora (Picos-PI)'])
    for r in registros_acessos():
        escritor.writerow([celula_csv(r['nome']), r['funcao'], r['data'], r['hora']])
    return Response('\ufeff' + arquivo.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=acessos_eduschedule.csv'})


# Conta os registros ativos e agrupa os alunos pelas três séries.
@app.get('/api/painel')
def painel():
    with conectar() as con:
        ativos = con.execute('SELECT COUNT(*) n FROM alunos WHERE ativo=1').fetchone()['n']
        inativos = con.execute('SELECT COUNT(*) n FROM alunos WHERE ativo=0').fetchone()['n']
        turmas = {r['turma']: r['n'] for r in con.execute('SELECT turma,COUNT(*) n FROM alunos WHERE ativo=1 GROUP BY turma')}
        professores = con.execute('SELECT COUNT(*) n FROM professores WHERE ativo=1').fetchone()['n']
    return jsonify(alunos=ativos,inativos=inativos,turmas=turmas,professores=professores)


# O filtro permite consultar alunos ativos ou descadastrados separadamente.
@app.get('/api/alunos')
def listar_alunos():
    status = request.args.get('status','ativos')
    if status not in ('ativos','inativos','todos'): return erro('Filtro inválido.')
    where = {'ativos':'WHERE ativo=1','inativos':'WHERE ativo=0','todos':''}[status]
    with conectar() as con:
        registros = con.execute(f'SELECT * FROM alunos {where} ORDER BY nome COLLATE NOCASE').fetchall()
    return jsonify([dict(r) for r in registros])


# O cadastro valida a turma e evita matrículas duplicadas.
@app.post('/api/alunos')
def criar_aluno():
    try: valores = validar_aluno(corpo())
    except ValueError as exc: return erro(str(exc))
    try:
        with conectar() as con:
            cursor = con.execute('INSERT INTO alunos(nome,turma,matricula) VALUES(?,?,?)',valores)
            novo_id = cursor.lastrowid
    except sqlite3.IntegrityError: return erro('Essa matrícula já existe.',409)
    return jsonify(id=novo_id,mensagem='Aluno cadastrado.'),201


# Atualiza os dados mantendo o mesmo identificador de aluno.
@app.put('/api/alunos/<int:aluno_id>')
def editar_aluno(aluno_id):
    try: valores = validar_aluno(corpo())
    except ValueError as exc: return erro(str(exc))
    try:
        with conectar() as con:
            existe = con.execute('SELECT id,turma FROM alunos WHERE id=? AND ativo=1',(aluno_id,)).fetchone()
            if not existe: return erro('Aluno ativo não encontrado.',404)
            if existe['turma'] != valores[1]:
                tem_historico = con.execute('SELECT 1 FROM notas WHERE aluno_id=? UNION SELECT 1 FROM presencas WHERE aluno_id=? LIMIT 1',(aluno_id,aluno_id)).fetchone()
                if tem_historico: return erro('Aluno com histórico não pode trocar de turma nesta versão. Descadastre e consulte a coordenação.',409)
            con.execute('UPDATE alunos SET nome=?,turma=?,matricula=? WHERE id=?',(*valores,aluno_id))
    except sqlite3.IntegrityError: return erro('Essa matrícula já existe.',409)
    return jsonify(mensagem='Cadastro atualizado.')


# Descadastrar significa alterar o status, não apagar o histórico.
@app.patch('/api/alunos/<int:aluno_id>/status')
def status_aluno(aluno_id):
    ativo = corpo().get('ativo')
    if type(ativo) is not bool: return erro('Informe ativo como verdadeiro ou falso.')
    with conectar() as con:
        cursor = con.execute('UPDATE alunos SET ativo=? WHERE id=?',(int(ativo),aluno_id))
        if not cursor.rowcount: return erro('Aluno não encontrado.',404)
    return jsonify(mensagem='Aluno reativado.' if ativo else 'Aluno descadastrado; histórico preservado.')


# Consulta os docentes para montar as listas de seleção.
@app.get('/api/professores')
def listar_professores():
    with conectar() as con:
        return jsonify([dict(r) for r in con.execute('SELECT * FROM professores WHERE ativo=1 ORDER BY nome COLLATE NOCASE')])


# Salva o professor antes de associar as disciplinas às turmas.
@app.post('/api/professores')
def criar_professor():
    nome = str(corpo().get('nome') or '').strip()
    if not 2 <= len(nome) <= 120: return erro('Informe o nome do professor.')
    with conectar() as con:
        novo = con.execute('INSERT INTO professores(nome) VALUES(?)',(nome,)).lastrowid
    return jsonify(id=novo,mensagem='Professor cadastrado.'),201


# Verifica os vínculos antes de retirar o professor do cadastro ativo.
@app.delete('/api/professores/<int:professor_id>')
def desativar_professor(professor_id):
    with conectar() as con:
        if con.execute('SELECT 1 FROM atribuicoes WHERE professor_id=?',(professor_id,)).fetchone():
            return erro('Retire primeiro as atribuições desse professor.',409)
        con.execute('UPDATE professores SET ativo=0 WHERE id=?',(professor_id,))
    return jsonify(mensagem='Professor descadastrado.')


# Junta professores, disciplinas e turmas para mostrar a distribuição de aulas.
@app.get('/api/atribuicoes')
def listar_atribuicoes():
    with conectar() as con:
        rows = con.execute('''SELECT a.*,p.nome professor FROM atribuicoes a
                              JOIN professores p ON p.id=a.professor_id
                              ORDER BY a.turma,a.disciplina''').fetchall()
    return jsonify([dict(r) for r in rows])


# Uma atribuição informa quem ensina uma disciplina, em qual turma e quantas vezes por semana.
@app.post('/api/atribuicoes')
def criar_atribuicao():
    """Vincula uma disciplina a uma turma ou às três de forma atômica."""
    d = corpo()
    try:
        professor_id = int(d.get('professor_id'))
        aulas = int(d.get('aulas_semana'))
    except (TypeError, ValueError):
        return erro('Informe professor e aulas semanais válidos.')

    turma = str(d.get('turma') or '').strip()
    disciplina = str(d.get('disciplina') or '').strip()
    turmas_escolhidas = TURMAS if turma == 'todas' else (turma,)
    if turma not in (*TURMAS, 'todas') or not 2 <= len(disciplina) <= 70 or not 1 <= aulas <= 20:
        return erro('Turma, disciplina ou quantidade de aulas inválida.')

    with conectar() as con:
        if not con.execute('SELECT 1 FROM professores WHERE id=? AND ativo=1', (professor_id,)).fetchone():
            return erro('Professor não encontrado.')

        # Verifica todos os limites ANTES de gravar; evita cadastro parcial.
        total_prof = con.execute(
            'SELECT COALESCE(SUM(aulas_semana),0) n FROM atribuicoes WHERE professor_id=?',
            (professor_id,)
        ).fetchone()['n']
        if total_prof + aulas * len(turmas_escolhidas) > 20:
            return erro('O professor excederia 20 aulas semanais somando todas as turmas.', 409)

        for t in turmas_escolhidas:
            total_turma = con.execute(
                'SELECT COALESCE(SUM(aulas_semana),0) n FROM atribuicoes WHERE turma=?', (t,)
            ).fetchone()['n']
            if total_turma + aulas > 25:
                return erro(f'A turma {t} excederia 25 aulas semanais.', 409)
            duplicada = con.execute(
                'SELECT 1 FROM atribuicoes WHERE turma=? AND disciplina=?', (t, disciplina)
            ).fetchone()
            if duplicada:
                return erro(f'{disciplina} já está cadastrada no {t}. Nada foi alterado.', 409)

        for t in turmas_escolhidas:
            con.execute(
                'INSERT INTO atribuicoes(professor_id,turma,disciplina,aulas_semana) VALUES(?,?,?,?)',
                (professor_id, t, disciplina, aulas)
            )
        con.execute('DELETE FROM horarios')  # Grade antiga fica desatualizada após novos vínculos.

    detalhe = 'nas três turmas' if turma == 'todas' else f'no {turma}'
    return jsonify(mensagem=f'Disciplina vinculada {detalhe}. Gere a grade novamente.'), 201


# Confere se existem registros vinculados antes de excluir uma distribuição.
@app.delete('/api/atribuicoes/<int:atribuicao_id>')
def excluir_atribuicao(atribuicao_id):
    with conectar() as con:
        if con.execute('SELECT 1 FROM notas WHERE atribuicao_id=? UNION SELECT 1 FROM chamadas WHERE atribuicao_id=? LIMIT 1',(atribuicao_id,atribuicao_id)).fetchone():
            return erro('Esta disciplina tem notas ou chamadas. Preserve o histórico; não é possível excluir.',409)
        con.execute('DELETE FROM horarios')
        cursor = con.execute('DELETE FROM atribuicoes WHERE id=?',(atribuicao_id,))
        if not cursor.rowcount: return erro('Vínculo não encontrado.',404)
    return jsonify(mensagem='Disciplina removida. Gere a grade novamente.')


# Consulta os bloqueios de dia e horário de cada professor.
@app.get('/api/restricoes')
def listar_restricoes():
    with conectar() as con:
        rows = con.execute('''SELECT r.*,p.nome professor FROM restricoes r
                              JOIN professores p ON p.id=r.professor_id
                              ORDER BY p.nome,r.dia,r.horario''').fetchall()
    return jsonify([dict(r) for r in rows])


# O bloqueio pertence ao professor, portanto vale para todas as turmas em que ele leciona.
@app.post('/api/restricoes')
def criar_restricao():
    d = corpo()
    try:
        professor = int(d.get('professor_id')); dia = int(d.get('dia')); horario = int(d.get('horario'))
    except (TypeError, ValueError): return erro('Selecione professor, dia e horário.')
    if dia not in range(5) or horario not in range(5): return erro('Dia ou horário inválido.')
    try:
        with conectar() as con:
            if not con.execute('SELECT 1 FROM professores WHERE id=? AND ativo=1',(professor,)).fetchone():
                return erro('Professor inválido.')
            con.execute('INSERT INTO restricoes(professor_id,dia,horario) VALUES(?,?,?)',(professor,dia,horario))
            con.execute('DELETE FROM horarios')
    except sqlite3.IntegrityError: return erro('Esse bloqueio já existe.',409)
    return jsonify(mensagem='Bloqueio salvo. Gere a grade novamente.'),201


# Retirar um bloqueio permite gerar outra grade com novas possibilidades.
@app.delete('/api/restricoes/<int:restricao_id>')
def excluir_restricao(restricao_id):
    with conectar() as con:
        con.execute('DELETE FROM restricoes WHERE id=?',(restricao_id,))
        con.execute('DELETE FROM horarios')
    return jsonify(mensagem='Bloqueio removido. Gere a grade novamente.')


# Cada aula vira uma tarefa; o algoritmo tenta encaixá-la sem sobrepor professor ou turma.
def montar_grade(atribuicoes, restricoes):
    """Algoritmo simples: sorteia horários válidos, com até 450 tentativas.
    Não é IA generativa; é distribuição automática baseada em regras.
    """
    proibidos = {(r['professor_id'],r['dia'],r['horario']) for r in restricoes}
    tarefas = []
    for a in atribuicoes:
        tarefas.extend([dict(a)] * a['aulas_semana'])
    if not tarefas: raise ValueError('Cadastre disciplinas e professores antes de gerar horários.')
    rng = random.Random()
    for _ in range(450):
        # Organiza primeiro docentes com menos horários possíveis.
        tarefas_ordenadas = tarefas[:]
        rng.shuffle(tarefas_ordenadas)
        tarefas_ordenadas.sort(key=lambda a: sum((a['professor_id'],d,h) not in proibidos for d in range(5) for h in range(5)))
        ocupados_turma = set()
        ocupados_prof = set()
        por_dia = {}
        resultado = []
        sucesso = True
        for a in tarefas_ordenadas:
            opcoes = []
            for dia in range(5):
                for hora in range(5):
                    if (a['turma'],dia,hora) in ocupados_turma or (a['professor_id'],dia,hora) in ocupados_prof:
                        continue
                    if (a['professor_id'],dia,hora) in proibidos: continue
                    repetidas = por_dia.get((a['id'],dia),0)
                    if repetidas >= 2: continue
                    # Distribui a disciplina ao longo da semana quando possível.
                    opcoes.append((repetidas * 8 + rng.random(),dia,hora))
            if not opcoes:
                sucesso = False; break
            _,dia,hora = min(opcoes)
            ocupados_turma.add((a['turma'],dia,hora))
            ocupados_prof.add((a['professor_id'],dia,hora))
            por_dia[(a['id'],dia)] = por_dia.get((a['id'],dia),0)+1
            resultado.append((a['turma'],dia,hora,a['id']))
        if sucesso: return resultado
    raise ValueError('Não foi possível montar uma grade com as restrições atuais. Reduza bloqueios ou cargas horárias.')


# Só substitui a grade depois que o algoritmo encontra uma distribuição válida.
@app.post('/api/horarios/gerar')
def gerar_horarios():
    with conectar() as con:
        atribuicoes = con.execute('SELECT * FROM atribuicoes').fetchall()
        restricoes = con.execute('SELECT * FROM restricoes').fetchall()
        try: grade = montar_grade(atribuicoes,restricoes)
        except ValueError as exc: return erro(str(exc),409)
        con.execute('DELETE FROM horarios')
        con.executemany('INSERT INTO horarios(turma,dia,horario,atribuicao_id) VALUES(?,?,?,?)',grade)
    return jsonify(mensagem=f'Grade gerada com {len(grade)} aulas, sem conflitos.')


# A exclusão remove somente a grade semanal, mantendo chamadas e notas.
@app.delete('/api/horarios')
def excluir_plano_de_aulas():
    """Apaga somente os horários gerados, sem apagar cadastros ou histórico."""
    with conectar() as con:
        total = con.execute('SELECT COUNT(*) AS n FROM horarios').fetchone()['n']
        con.execute('DELETE FROM horarios')
    return jsonify(mensagem=f'Plano de aulas excluído ({total} horários removidos). Cadastros e histórico preservados.')


# Devolve a grade com os nomes necessários para a tabela da interface.
@app.get('/api/horarios')
def listar_horarios():
    with conectar() as con:
        rows = con.execute('''SELECT h.*,a.disciplina,p.nome professor FROM horarios h
                              JOIN atribuicoes a ON a.id=h.atribuicao_id
                              JOIN professores p ON p.id=a.professor_id
                              ORDER BY h.turma,h.dia,h.horario''').fetchall()
    return jsonify([dict(r) for r in rows])


# Lê os parâmetros usados nos cálculos escolares.
@app.get('/api/configuracoes')
def configuracoes():
    with conectar() as con:
        return jsonify(dict(con.execute('SELECT * FROM configuracoes WHERE id=1').fetchone()))


# Valida os novos limites antes de atualizar a configuração.
@app.put('/api/configuracoes')
def atualizar_configuracoes():
    d = corpo()
    try:
        media = float(d.get('media_minima')); frequencia = float(d.get('frequencia_minima'))
        semanas = int(d.get('semanas_letivas'))
    except (TypeError, ValueError): return erro('Informe números válidos.')
    if not (0 <= media <= 10 and 1 <= frequencia <= 100 and 1 <= semanas <= 52):
        return erro('Valores fora dos limites permitidos.')
    with conectar() as con:
        con.execute('UPDATE configuracoes SET media_minima=?, frequencia_minima=?, semanas_letivas=? WHERE id=1',
                    (media,frequencia,semanas))
    return jsonify(mensagem='Configurações salvas.')


# Reúne as notas por aluno e calcula o desempenho conforme os bimestres lançados.
@app.get('/api/notas')
def listar_notas():
    turma = request.args.get('turma')
    atribuicao_id = request.args.get('atribuicao_id',type=int)
    if turma not in TURMAS or not atribuicao_id: return erro('Selecione turma e disciplina.')
    with conectar() as con:
        a = con.execute('SELECT * FROM atribuicoes WHERE id=? AND turma=?',(atribuicao_id,turma)).fetchone()
        if not a: return erro('Disciplina não pertence à turma.')
        media_min = con.execute('SELECT media_minima FROM configuracoes WHERE id=1').fetchone()['media_minima']
        alunos = con.execute('SELECT id,nome FROM alunos WHERE turma=? AND ativo=1 ORDER BY nome COLLATE NOCASE',(turma,)).fetchall()
        notas = con.execute('SELECT aluno_id,bimestre,nota FROM notas WHERE atribuicao_id=?',(atribuicao_id,)).fetchall()
    mapa = {(n['aluno_id'],n['bimestre']):n['nota'] for n in notas}
    resultado = []
    for aluno in alunos:
        vals = [mapa.get((aluno['id'],i)) for i in range(1,5)]
        preenchidas = [v for v in vals if v is not None]
        media = round(sum(preenchidas)/len(preenchidas),2) if preenchidas else None
        situacao = ('Sem notas' if media is None else
                    ('Em andamento' if len(preenchidas)<4 else ('Na média' if media>=media_min else 'Abaixo da média')))
        resultado.append({'id':aluno['id'],'nome':aluno['nome'],'notas':vals,'media':media,'situacao':situacao})
    return jsonify(alunos=resultado,media_minima=media_min)


# Salva ou atualiza os valores de cada bimestre sem duplicar registros.
@app.put('/api/notas')
def salvar_notas():
    d = corpo()
    try:
        atrib = int(d.get('atribuicao_id')); bimestre = int(d.get('bimestre'))
    except (TypeError,ValueError): return erro('Selecione disciplina e bimestre.')
    if bimestre not in range(1,5): return erro('Bimestre inválido.')
    itens = d.get('notas')
    if not isinstance(itens,list): return erro('Envie a lista de notas.')
    with conectar() as con:
        a = con.execute('SELECT turma FROM atribuicoes WHERE id=?',(atrib,)).fetchone()
        if not a: return erro('Disciplina inválida.')
        for item in itens:
            try:
                aluno_id = int(item['aluno_id'])
                valor = item.get('nota')
                if valor is not None and valor != '':
                    valor = float(valor)
                    if not math.isfinite(valor) or not 0 <= valor <= 10: return erro('Cada nota deve estar entre 0 e 10.')
                else: valor = None
            except (ValueError,TypeError,KeyError): return erro('Nota ou aluno inválido.')
            if not con.execute('SELECT 1 FROM alunos WHERE id=? AND turma=? AND ativo=1',(aluno_id,a['turma'])).fetchone():
                return erro('Aluno não pertence a essa turma.')
            if valor is None:
                con.execute('DELETE FROM notas WHERE aluno_id=? AND atribuicao_id=? AND bimestre=?',(aluno_id,atrib,bimestre))
            else:
                con.execute('''INSERT INTO notas VALUES(?,?,?,?) ON CONFLICT(aluno_id,atribuicao_id,bimestre)
                               DO UPDATE SET nota=excluded.nota''',(aluno_id,atrib,bimestre,valor))
    return jsonify(mensagem='Notas salvas com sucesso.')


# O percentual usa chamadas registradas; o saldo de faltas usa a carga anual estimada.
def resumo_frequencia(con, aluno_id, atrib_id, aulas_semana):
    cfg = con.execute('SELECT * FROM configuracoes WHERE id=1').fetchone()
    totais = con.execute('''SELECT COUNT(*) total,
                COALESCE(SUM(CASE WHEN p.presente=0 THEN 1 ELSE 0 END),0) faltas
                FROM presencas p JOIN chamadas c ON c.id=p.chamada_id
                WHERE p.aluno_id=? AND c.atribuicao_id=?''',(aluno_id,atrib_id)).fetchone()
    realizadas = totais['total']; faltas = totais['faltas']
    previstas = aulas_semana * cfg['semanas_letivas']
    # Limite ilustrativo com carga semanal e semanas letivas configuradas.
    max_faltas = math.floor(previstas*(100-cfg['frequencia_minima'])/100 + 1e-9)
    restante = max(0,max_faltas-faltas)
    percentual = round(100*(realizadas-faltas)/realizadas,1) if realizadas else None
    return {'realizadas':realizadas,'faltas':faltas,'percentual':percentual,
            'aulas_previstas':previstas,'limite_faltas':max_faltas,
            'faltas_restantes':restante,'alerta':faltas>max_faltas}


# Aplica o cálculo de frequência aos alunos ativos da turma e disciplina selecionadas.
@app.get('/api/frequencia/resumo')
def frequencia_resumo():
    turma = request.args.get('turma'); atrib = request.args.get('atribuicao_id',type=int)
    if turma not in TURMAS or not atrib: return erro('Selecione turma e disciplina.')
    with conectar() as con:
        a = con.execute('SELECT * FROM atribuicoes WHERE id=? AND turma=?',(atrib,turma)).fetchone()
        if not a: return erro('Disciplina não corresponde à turma.')
        alunos = con.execute('SELECT id,nome FROM alunos WHERE turma=? AND ativo=1 ORDER BY nome',(turma,)).fetchall()
        resultado = [dict(aluno)|resumo_frequencia(con,aluno['id'],atrib,a['aulas_semana']) for aluno in alunos]
    return jsonify(alunos=resultado)


# Busca a aula da grade ou uma chamada já registrada para a data escolhida.
@app.get('/api/frequencia/chamada')
def ler_chamada():
    turma = request.args.get('turma'); data_str = request.args.get('data'); horario = request.args.get('horario',type=int)
    if turma not in TURMAS or horario not in range(5): return erro('Selecione turma e horário.')
    try: dia = date.fromisoformat(data_str)
    except (ValueError,TypeError): return erro('Data inválida.')
    if dia.weekday() not in range(5): return erro('Selecione um dia de segunda a sexta.')
    with conectar() as con:
        aula = con.execute('''SELECT h.atribuicao_id,a.disciplina,p.nome professor
                              FROM horarios h JOIN atribuicoes a ON a.id=h.atribuicao_id
                              JOIN professores p ON p.id=a.professor_id
                              WHERE h.turma=? AND h.dia=? AND h.horario=?''',(turma,dia.weekday(),horario)).fetchone()
        if not aula: return erro('Não há aula na grade nesse horário. Gere a grade primeiro.',404)
        chamada = con.execute('SELECT id,atribuicao_id FROM chamadas WHERE dia_aula=? AND turma=? AND horario=?',
                              (data_str,turma,horario)).fetchone()
        if chamada and chamada['atribuicao_id'] != aula['atribuicao_id']:
            return erro('Já existe chamada de outra disciplina nesse horário. Preserve o histórico.',409)
        alunos = con.execute('SELECT id,nome FROM alunos WHERE turma=? AND ativo=1 ORDER BY nome',(turma,)).fetchall()
        existentes = {}
        if chamada:
            existentes = {r['aluno_id']:bool(r['presente']) for r in con.execute('SELECT aluno_id,presente FROM presencas WHERE chamada_id=?',(chamada['id'],))}
    return jsonify(disciplina=aula['disciplina'],professor=aula['professor'],
                   atribuicao_id=aula['atribuicao_id'],
                   alunos=[{'id':a['id'],'nome':a['nome'],'presente':existentes.get(a['id'])} for a in alunos])


# Confere os alunos da turma e grava uma presença ou falta por aluno.
@app.put('/api/frequencia/chamada')
def salvar_chamada():
    d = corpo(); turma = d.get('turma'); data_str = d.get('data')
    try: horario = int(d.get('horario')); dia = date.fromisoformat(data_str)
    except (ValueError,TypeError): return erro('Data ou horário inválido.')
    if turma not in TURMAS or dia.weekday() not in range(5) or horario not in range(5): return erro('Turma, dia ou horário inválido.')
    lista = d.get('alunos')
    if not isinstance(lista,list): return erro('Lista de presença inválida.')
    with conectar() as con:
        a = con.execute('SELECT atribuicao_id FROM horarios WHERE turma=? AND dia=? AND horario=?',(turma,dia.weekday(),horario)).fetchone()
        if not a: return erro('Nenhuma aula configurada para este horário.',404)
        antiga = con.execute('SELECT id,atribuicao_id FROM chamadas WHERE dia_aula=? AND turma=? AND horario=?',(data_str,turma,horario)).fetchone()
        if antiga and antiga['atribuicao_id'] != a['atribuicao_id']: return erro('Chamada antiga pertence a outra disciplina.',409)
        ids = {r['id'] for r in con.execute('SELECT id FROM alunos WHERE turma=? AND ativo=1',(turma,))}
        if len(lista) != len(ids): return erro('Registre presença ou falta para todos os alunos ativos.')
        vistos = set(); registros = []
        for item in lista:
            if not isinstance(item,dict) or type(item.get('presente')) is not bool: return erro('Marque presença ou falta para cada aluno.')
            try: aluno_id = int(item['id'])
            except (KeyError,TypeError,ValueError): return erro('Aluno inválido.')
            if aluno_id not in ids or aluno_id in vistos: return erro('Lista contém aluno inválido ou repetido.')
            vistos.add(aluno_id); registros.append((aluno_id,int(item['presente'])))
        if not antiga:
            chamada_id = con.execute('INSERT INTO chamadas(dia_aula,turma,horario,atribuicao_id) VALUES(?,?,?,?)',
                                     (data_str,turma,horario,a['atribuicao_id'])).lastrowid
        else: chamada_id = antiga['id']
        con.executemany('''INSERT INTO presencas(chamada_id,aluno_id,presente) VALUES(?,?,?)
                           ON CONFLICT(chamada_id,aluno_id) DO UPDATE SET presente=excluded.presente''',
                        [(chamada_id,aluno_id,presente) for aluno_id,presente in registros])
    return jsonify(mensagem='Chamada salva.')


iniciar_banco()
if __name__ == '__main__':
    app.run(debug=False)
