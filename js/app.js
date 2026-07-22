const app = {
    user: null,
    currentCategory: null,
    currentAssunto: null,
    questoes: [],
    currentIndex: 0,

    init() {
        const urlParams = new URLSearchParams(window.location.search);
        
        // Checa login na URL ou localStorage
        const uid = urlParams.get('uid') || localStorage.getItem('sedes_uid');
        const user = urlParams.get('user') || localStorage.getItem('sedes_user');

        if (uid && user) {
            this.user = { id: parseInt(uid), name: user };
            localStorage.setItem('sedes_uid', uid);
            localStorage.setItem('sedes_user', user);
            this.showUserBar();
            
            // Checa rota na URL
            const catId = urlParams.get('cat');
            const assuntoId = urlParams.get('assunto');
            const qNum = urlParams.get('q');

            if (assuntoId) {
                this.loadQuiz(parseInt(assuntoId), qNum ? parseInt(qNum) - 1 : 0);
            } else if (catId) {
                this.loadTopics(parseInt(catId));
            } else {
                this.showCategories();
            }
        } else {
            this.showView('login');
        }
    },

    showToast(msg) {
        const toast = document.getElementById('toast');
        toast.innerText = msg;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    },

    updateURL() {
        const url = new URL(window.location.href);
        if (this.user) {
            url.searchParams.set('uid', this.user.id);
            url.searchParams.set('user', this.user.name);
        }
        if (this.currentCategory) {
            url.searchParams.set('cat', this.currentCategory.id);
        } else {
            url.searchParams.delete('cat');
        }
        if (this.currentAssunto) {
            url.searchParams.set('assunto', this.currentAssunto);
            url.searchParams.set('q', this.currentIndex + 1);
        } else {
            url.searchParams.delete('assunto');
            url.searchParams.delete('q');
        }
        window.history.replaceState({}, '', url.toString());
    },

    copyDirectLink() {
        this.updateURL();
        const fullURL = window.location.href;
        navigator.clipboard.writeText(fullURL).then(() => {
            this.showToast('🔗 Link direto copiado para a área de transferência!');
        }).catch(() => {
            prompt('Copie o link abaixo:', fullURL);
        });
    },

    showUserBar() {
        document.getElementById('user-bar').style.display = 'flex';
        document.getElementById('user-name-display').innerText = this.user.name;
    },

    logout() {
        localStorage.removeItem('sedes_uid');
        localStorage.removeItem('sedes_user');
        this.user = null;
        window.location.href = window.location.pathname;
    },

    async handleLogin(e) {
        e.preventDefault();
        const loginInput = document.getElementById('input-login').value;
        const senhaInput = document.getElementById('input-senha').value;

        try {
            const res = await fetch(`/api/index?action=login&login=${encodeURIComponent(loginInput)}&senha=${encodeURIComponent(senhaInput)}`);
            const data = await res.json();
            if (data.success) {
                this.user = { id: data.user_id, name: data.username };
                localStorage.setItem('sedes_uid', data.user_id);
                localStorage.setItem('sedes_user', data.username);
                this.showUserBar();
                this.showCategories();
            } else {
                alert(data.error || 'Erro no login.');
            }
        } catch (err) {
            alert('Erro ao conectar ao servidor.');
        }
    },

    showView(viewName) {
        ['login', 'categories', 'topics', 'quiz'].forEach(v => {
            document.getElementById(`view-${v}`).style.display = (v === viewName) ? 'block' : 'none';
        });
        this.updateURL();
    },

    async showCategories() {
        this.currentCategory = null;
        this.currentAssunto = null;
        document.getElementById('header-subtitle').innerText = 'Escolha a Área de Conhecimento';
        this.showView('categories');

        try {
            const res = await fetch('/api/index?action=categorias');
            const data = await res.json();
            if (data.success) {
                const grid = document.getElementById('categories-grid');
                grid.innerHTML = '';
                data.categorias.forEach(cat => {
                    grid.innerHTML += `
                        <div class="dash-card">
                            <div class="dash-title">🏛️ ${cat.nome}</div>
                            <button class="btn btn-block" onclick="app.loadTopics(${cat.id}, '${cat.nome}')">Acessar Assuntos ➡️</button>
                        </div>
                    `;
                });
            }
        } catch (err) {
            console.error(err);
        }
    },

    showTopics() {
        if (this.currentCategory && this.currentCategory.id) {
            this.loadTopics(this.currentCategory.id, this.currentCategory.nome);
        } else {
            this.showCategories();
        }
    },

    async loadTopics(catId, catNome) {
        this.currentCategory = { id: catId, nome: catNome };
        this.currentAssunto = null;
        document.getElementById('header-subtitle').innerText = `Pilares: ${catNome || ''}`;
        this.showView('topics');

        try {
            const res = await fetch(`/api/index?action=dashboard&categoria_id=${catId}&usuario_id=${this.user.id}`);
            const data = await res.json();
            if (data.success) {
                const grid = document.getElementById('topics-grid');
                grid.innerHTML = '';
                if (data.assuntos.length === 0) {
                    grid.innerHTML = '<p style="text-align:center; width:100%; color:#94a3b8;">Nenhum assunto com questões neste pilar.</p>';
                    return;
                }
                data.assuntos.forEach(ass => {
                    const progresso = ass.total > 0 ? (ass.respondidas / ass.total) : 0;
                    const acuracia = ass.respondidas > 0 ? (ass.acertos / ass.respondidas) : 0;

                    const circExt = 565.48;
                    const circInt = 439.82;
                    const offsetExt = circExt * (1 - progresso);
                    const offsetInt = circInt * (1 - acuracia);

                    const svgChart = `
                        <div style="display: flex; justify-content: center; margin-bottom: 12px;">
                        <svg width="180" height="180" viewBox="0 0 200 200">
                          <circle cx="100" cy="100" r="90" fill="none" stroke="#334155" stroke-width="12"/>
                          <circle cx="100" cy="100" r="70" fill="none" stroke="#334155" stroke-width="12"/>
                          <circle cx="100" cy="100" r="90" fill="none" stroke="#3b82f6" stroke-width="12" stroke-dasharray="${circExt}" stroke-dashoffset="${offsetExt}" stroke-linecap="round" transform="rotate(-90 100 100)"/>
                          <circle cx="100" cy="100" r="70" fill="none" stroke="#10b981" stroke-width="12" stroke-dasharray="${circInt}" stroke-dashoffset="${offsetInt}" stroke-linecap="round" transform="rotate(-90 100 100)"/>
                          <text x="100" y="95" font-family="Inter" font-size="28" font-weight="bold" fill="#10b981" text-anchor="middle">${Math.round(acuracia*100)}%</text>
                          <text x="100" y="115" font-family="Inter" font-size="12" fill="#94a3b8" text-anchor="middle">Acertos</text>
                          <text x="100" y="140" font-family="Inter" font-size="12" font-weight="bold" fill="#60a5fa" text-anchor="middle">${ass.respondidas} / ${ass.total} Feitas</text>
                        </svg>
                        </div>
                    `;

                    grid.innerHTML += `
                        <div class="dash-card">
                            <div class="dash-title">${ass.nome}</div>
                            ${svgChart}
                            <button class="btn btn-block" onclick="app.loadQuiz(${ass.id}, 0)">Estudar Agora ➡️</button>
                            ${ass.respondidas > 0 ? `<button class="btn btn-secondary btn-block" style="margin-top:8px;" onclick="app.resetTopic(${ass.id})">🔄 Refazer</button>` : ''}
                        </div>
                    `;
                });
            }
        } catch (err) {
            console.error(err);
        }
    },

    async resetTopic(assuntoId) {
        if (!confirm('Deseja refazer todas as questões deste assunto?')) return;
        try {
            await fetch('/api/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'reset', assunto_id: assuntoId, usuario_id: this.user.id })
            });
            this.loadTopics(this.currentCategory.id, this.currentCategory.nome);
        } catch (err) {
            alert('Erro ao resetar.');
        }
    },

    async loadQuiz(assuntoId, targetIndex = 0) {
        this.currentAssunto = assuntoId;
        this.showView('quiz');

        try {
            const res = await fetch(`/api/index?action=questoes&assunto_id=${assuntoId}&usuario_id=${this.user.id}`);
            const data = await res.json();
            if (data.success) {
                document.getElementById('header-subtitle').innerText = `Matéria: ${data.assunto_nome}`;
                this.questoes = data.questoes;
                
                // Se a posição target for 0 e houver respondidas, vai para a primeira não respondida
                if (targetIndex === 0) {
                    const firstUnanswered = this.questoes.findIndex(q => !q.resposta_usuario);
                    this.currentIndex = firstUnanswered !== -1 ? firstUnanswered : 0;
                } else {
                    this.currentIndex = Math.max(0, Math.min(targetIndex, this.questoes.length - 1));
                }

                this.renderQuestion();
            }
        } catch (err) {
            console.error(err);
        }
    },

    renderQuestion() {
        if (!this.questoes || this.questoes.length === 0) {
            document.getElementById('quiz-question-text').innerText = 'Nenhuma questão cadastrada para este assunto.';
            return;
        }

        const q = this.questoes[this.currentIndex];
        const total = this.questoes.length;
        const currentNum = this.currentIndex + 1;

        // Atualiza progresso
        document.getElementById('quiz-progress-text').innerText = `Questão ${currentNum} de ${total}`;
        document.getElementById('quiz-progress-percent').innerText = `${Math.round((currentNum / total) * 100)}%`;
        document.getElementById('quiz-progress-fill').style.width = `${(currentNum / total) * 100}%`;

        // Botões de navegação
        document.getElementById('btn-prev').disabled = (this.currentIndex === 0);
        document.getElementById('btn-next').disabled = (this.currentIndex === total - 1);

        // Enunciado
        document.getElementById('quiz-question-text').innerText = q.enunciado;

        // Alternativas
        const altsContainer = document.getElementById('quiz-alternatives');
        altsContainer.innerHTML = '';

        const respSalva = q.resposta_usuario;

        q.alternativas.forEach(alt => {
            const letra = alt[0];
            let cssClass = 'alt-option';

            if (respSalva) {
                const correta = q.resposta_correta.toUpperCase();
                const selecionada = respSalva.resposta_dada.toUpperCase();

                if (letra === correta) {
                    cssClass += ' correct';
                } else if (letra === selecionada) {
                    cssClass += ' incorrect';
                }
            }

            const explicacoes = q.explicacoes || {};
            const expTexto = (respSalva && explicacoes[letra]) ? explicacoes[letra] : '';

            altsContainer.innerHTML += `
                <div class="${cssClass}" onclick="${!respSalva ? `app.selectAnswer('${letra}')` : ''}">
                    <div class="alt-header">${alt}</div>
                    ${expTexto ? `<div class="alt-explanation">${expTexto}</div>` : ''}
                </div>
            `;
        });

        this.updateURL();
    },

    async selectAnswer(letra) {
        const q = this.questoes[this.currentIndex];
        try {
            const res = await fetch('/api/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action: 'responder',
                    questao_id: q.id,
                    resposta: letra,
                    usuario_id: this.user.id
                })
            });
            const data = await res.json();
            if (data.success) {
                q.resposta_usuario = { resposta_dada: letra, correta: data.correta };
                this.renderQuestion();
            }
        } catch (err) {
            alert('Erro ao salvar resposta.');
        }
    },

    prevQuestion() {
        if (this.currentIndex > 0) {
            this.currentIndex--;
            this.renderQuestion();
        }
    },

    nextQuestion() {
        if (this.currentIndex < this.questoes.length - 1) {
            this.currentIndex++;
            this.renderQuestion();
        }
    }
};

window.onload = () => app.init();
