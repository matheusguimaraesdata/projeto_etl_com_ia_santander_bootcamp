# Como `users-api-python` e `etl_com_ia` se encaixam

São dois repositórios separados, com histórico e propósito próprios, mas que só fazem sentido completo juntos. Vale explicar por quê, porque não é óbvio olhando cada um isolado.

## Quem é quem

**`users-api-python`** é a fonte da verdade. FastAPI + SQLModel + Postgres, com usuários, contas, cartões e um histórico de "news" por usuário. Ela não sabe nada sobre campanha, segmento ou Gemini — é só uma API de dados, com autenticação e um endpoint de analytics.

**`projeto_etl_com_ia_santander_bootcamp`** não guarda dado nenhum. Ele lê a base inteira da API, decide quem entra em qual campanha, gera a mensagem com IA e escreve o resultado de volta na mesma API. Sem a API, o ETL não tem o que processar. Sem o ETL, a API é só um CRUD sem nenhuma inteligência de negócio em cima.

## Por que dois repositórios, e não um monorepo

Cheguei a pensar nisso, mas as duas coisas evoluem em ritmos diferentes e têm dependências diferentes (a API precisa de SQLModel/Postgres; o ETL precisa de Pandas/google-genai). Separar deixa claro, olhando de fora, que são duas responsabilidades distintas — o que também é mais parecido com como equipes reais de dados costumam dividir "quem serve o dado" de "quem processa o dado".

## Onde o contrato entre os dois vive

O ETL depende de três coisas específicas da API, e se qualquer uma mudar sem aviso, o ETL quebra:

- `GET /usuario` — precisa aceitar `offset`/`limit` e devolver uma lista simples (sem contagem total; é por isso que o `extract.py` pagina até uma página vir menor que o limite pedido, em vez de confiar num campo `total`)
- `POST /auth/login` — precisa devolver `access_token` no corpo
- `PATCH /usuario/{id}` — precisa aceitar atualização parcial só do campo `news`

Não existe teste automatizado que rode contra os dois repositórios ao mesmo tempo hoje — os testes do ETL mockam a API inteiramente. Isso é uma limitação real: se eu mudar o schema de resposta da API sem atualizar o ETL, só vou descobrir rodando manualmente contra a API real, não numa suíte de CI. Documentando aqui porque é o tipo de coisa que uma sabatina técnica pode perguntar direto: "e se um dos dois mudar, como você saberia?" — hoje, honestamente, eu não saberia até rodar.

## A migração de infraestrutura que afetou os dois

A API rodava no Railway. O plano gratuito deles mudou de modelo em 2026 (virou trial de crédito + US$1/mês) e o deploy parou de funcionar sem aviso prévio. Migrei pra Render, que tem free tier real sem cartão — só que com uma troca: o serviço "dorme" depois de 15 minutos sem uso, e a primeira requisição depois disso demora uns 30-60 segundos.

Isso não afeta só a API — afeta diretamente o ETL. Se o `settings.py` do ETL usasse um timeout curto demais, a primeira chamada de uma execução agendada falharia sempre que a API estivesse "dormindo". É por isso que o workflow do GitHub Actions do ETL tem um passo explícito de "acordar a API" (um `curl` com retry) antes de rodar o pipeline de verdade — não é enfeite, é consequência direta de rodar em cima de infraestrutura gratuita com essa limitação.

## O que eu faria diferente se fosse produção de verdade

Um contrato de API versionado (ou um schema compartilhado, tipo OpenAPI gerado automaticamente e consumido pelo ETL) em vez de os dois lados assumirem o formato um do outro por convenção. Hoje funciona porque sou eu que mantenho os dois lados — numa equipe de verdade, com pessoas diferentes em cada repositório, essa falta de contrato formal quebraria rápido.]
