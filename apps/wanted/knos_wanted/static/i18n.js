// Knos UI strings. Seven languages; "ar" renders right-to-left. Keys missing from a language fall back to English.
"use strict";
window.KNOS_I18N = {
  langs: { en: "English", fr: "Français", es: "Español", pt: "Português", ar: "العربية", hi: "हिन्दी", zh: "中文" },
  rtl: ["ar"],
  en: {
    tag: "Proven research, funded products",
    
    sign_in: "Sign in", sign_out: "Sign out",
    skip: "Skip to the app", 
    via_preorder: "pre-order signed by the buyer's passkey (test money)", via_funder: "funder money: held by a funder for this milestone", via_blink: "Solana Action (Blink)",
    hero_t: "Research that works, waiting for a market.",
    hero_p: "Paste a paper. Qloo shows who would buy its product, where, and at what price.",
    
    cross_t: "Start a crossing", cross_ref: "Paper id (DOI, arXiv, PubMed, OpenAlex, patent)", cross_or: "or your own idea",
    cross_idea: "Describe the product idea", cross_place: "Launch market (optional)", cross_product: "Product phrase (optional)",
    cross_go: "Run the crossing", cross_busy: "The agent is crossing",
    timeline_t: "The crossing, live", open_product: "Open the product page",
    try: "Try:",
    buy_t: "Pre-order", 
    buy_wallet: "With your wallet", buy_wallet_p: "A Solana Action: any wallet signs. This server never holds your key.",
    
    buy_btn: "Pre-order with a wallet", buy_demo_btn: "Pre-order with my passkey", units: "Units",
    for_l: "For", where_l: "Launching in", price_l: "Price", goal_l: "Funding goal", unserved_l: "Who the leader does not serve",
    fund_t: "Back a milestone", fund_p: "Your money is held until the proof passes. The maker is paid only on proof.",
    
    contribute_t: "Open work", contribute_p: "Join a round or make a milestone. Work is checked, then paid.",
    contribute_none: "No open rounds on this server right now. Milestones below need evidence.",
    make_t: "Milestones and payouts", make_p: "Post a public page with the claim id. Referees check it; the held money is released.",
    agents_t: "For agents", agents_p: "The same crossing, pre-order and milestone flows over the Model Context Protocol.",
    agents_add: "Add this server by URL in Claude, Cursor or any MCP client:",
    verify_link: "How we verify", lang_l: "Language",
    test_money: "Devnet test money: no real funds", status_live: "Qloo: live", status_limited: "Qloo: limited", status_off: "Qloo: off",
    loading: "Working", empty: "Nothing here yet", err_signin: "Sign in first.",
    receipt_t: "Held until the proof passes", evidence_pin: "Evidence pin on chain", page_sha: "Evidence page sha256",
    milestone_prove: "Prove and release", evidence_url: "Evidence page URL", claim_id: "Claim id",
    reserve: "Reserve", target: "Target", released: "released", locked: "locked", refuse: "Refused", open_v: "Open for pre-orders",
    cannot: "Cannot decide", footer: "Qloo taste data is read on the server only. Money is held on Solana devnet in test units: no real money. MIT licensed.",
    pk_new: "Create a passkey wallet", pk_use: "Sign in with my passkey",
    pk_note: "No seed phrase: the passkey is your wallet (a LazorKit smart wallet on devnet). Every payment is approved on your device.",
    
    mem_search: "Search everything Knos remembers",
    wallet_t: "Your passkey wallet", faucet_btn: "Get 25 devnet test units", claim_btn: "I make this: claim the milestone with my passkey", claimed: "Maker's passkey", pk_sign: "Approve on your passkey",
    
    
    
    home_own: "Cross your own paper",
    back_btn: "Back it",
    fundm_btn: "Fund a milestone",
    contrib_btn: "Contribute",
    backed_l: "pre-ordered",
    held_l: "held for the milestone",
    maker_wanted: "maker wanted",
    of: "of",
    checking: "Getting live demand for this product",
    open_project: "Open the project",
    no_maker: "No maker yet. Commit now: you pay only when it is made.",
    amc_btn: "Commit to buy",
    committed_l: "Committed",
    amc_rule: "paid to the maker only when it verifies",
    name_l: "Your name",
    pk_none: "This browser has no passkeys. Try a phone or another browser.",
    
    
    
    
    make_need: "Milestones that need a maker",
    make_btn: "Make it",
    open_ms: "open milestones",
    attempt_l: "Your attempt",
    paid_passkey: "paid to your passkey wallet"
  },
  fr: {
    tag: "Recherche prouvée, produits financés",
    
    sign_in: "Connexion", sign_out: "Déconnexion",
    skip: "Aller à l'application", 
    via_preorder: "précommande signée par la clé d'accès de l'acheteur (argent de test)", via_funder: "argent d'un financeur, retenu pour ce jalon", via_blink: "Action Solana (Blink)",
    hero_t: "Une recherche qui marche, en attente d'un marché.",
    hero_p: "Collez un article. Qloo montre qui achèterait son produit, où et à quel prix.",
    
    cross_t: "Lancer une traversée", cross_ref: "Identifiant de l'article (DOI, arXiv, PubMed, OpenAlex, brevet)", cross_or: "ou votre propre idée",
    cross_idea: "Décrivez l'idée de produit", cross_place: "Marché de lancement (facultatif)", cross_product: "Formulation du produit (facultatif)",
    cross_go: "Lancer la traversée", cross_busy: "L'agent traverse",
    timeline_t: "La traversée, en direct", open_product: "Ouvrir la page produit",
    try: "Essayez :",
    buy_t: "Précommander", 
    buy_wallet: "Avec votre portefeuille", buy_wallet_p: "Une Solana Action : n'importe quel portefeuille signe. Ce serveur ne détient jamais votre clé.",
    
    buy_btn: "Précommander avec un portefeuille", buy_demo_btn: "Précommander avec ma clé d'accès", units: "Unités",
    for_l: "Pour", where_l: "Lancement à", price_l: "Prix", goal_l: "Objectif", unserved_l: "Public que le leader ne sert pas",
    fund_t: "Soutenir un jalon", fund_p: "Votre argent est retenu jusqu'à ce que la preuve soit validée. Le fabricant n'est payé que sur preuve.",
    
    contribute_t: "Travail ouvert", contribute_p: "Rejoignez une manche ou fabriquez une étape. Le travail est jugé, puis payé.",
    contribute_none: "Aucune manche ouverte sur ce serveur. Les jalons ci-dessous attendent des preuves.",
    make_t: "Jalons et paiements", make_p: "Publiez une page publique avec l'identifiant. Les arbitres vérifient ; l'argent retenu est versé.",
    agents_t: "Pour les agents", agents_p: "Les mêmes flux de traversée, précommande et jalon via le Model Context Protocol.",
    agents_add: "Ajoutez ce serveur par URL dans Claude, Cursor ou tout client MCP :",
    verify_link: "Comment nous vérifions", lang_l: "Langue",
    test_money: "Argent de test devnet: aucun fonds réel", status_live: "Qloo : actif", status_off: "Qloo : inactif",
    loading: "En cours", empty: "Rien ici pour l'instant", err_signin: "Connectez-vous d'abord.",
    receipt_t: "Retenu jusqu'à la preuve", evidence_pin: "Empreinte de preuve sur chaîne", page_sha: "sha256 de la page de preuve",
    milestone_prove: "Prouver et libérer", evidence_url: "URL de la page de preuve", claim_id: "Identifiant",
    reserve: "Réserve", target: "Objectif", released: "libéré", locked: "verrouillé", refuse: "Refusé", open_v: "Précommandes ouvertes",
    cannot: "Indécidable", footer: "Les données Qloo sont lues côté serveur uniquement. Argent retenu sur Solana devnet en unités de test : pas d'argent réel. Licence MIT.",
    pk_new: "Créer un portefeuille passkey", pk_use: "Me connecter par passkey",
    pk_note: "Sans phrase secrète : la clé d'accès est votre portefeuille (portefeuille intelligent LazorKit sur devnet). Chaque paiement est approuvé sur votre appareil.",
    
    mem_search: "Chercher dans la mémoire de Knos",
    wallet_t: "Votre portefeuille à clé d'accès", faucet_btn: "Obtenir 25 unités de test devnet", claim_btn: "Je le fabrique : revendiquer le jalon avec ma clé d'accès", claimed: "Clé d'accès du fabricant", pk_sign: "Approuvez avec votre clé d'accès",
    
    
    
    home_own: "Croisez votre propre article",
    back_btn: "Soutenir",
    fundm_btn: "Financer une étape",
    contrib_btn: "Contribuer",
    backed_l: "précommandés",
    held_l: "retenus pour l'étape",
    maker_wanted: "fabricant recherché",
    of: "sur",
    checking: "Lecture de la demande en direct",
    open_project: "Ouvrir le projet",
    no_maker: "Pas encore de fabricant. Engagez-vous : vous payez seulement quand il est fait.",
    amc_btn: "M'engager à acheter",
    committed_l: "Engagé",
    amc_rule: "payé au fabricant seulement après vérification",
    name_l: "Votre nom",
    pk_none: "Ce navigateur n'a pas de clés d'accès. Essayez un téléphone ou un autre navigateur.",
    
    
    
    
    make_need: "Étapes qui attendent un fabricant",
    make_btn: "Je le fabrique",
    open_ms: "étapes ouvertes",
    attempt_l: "Votre tentative",
    paid_passkey: "payé sur votre portefeuille à clé d'accès"
  },
  es: {
    tag: "Investigación probada, productos financiados",
    
    sign_in: "Iniciar sesión", sign_out: "Cerrar sesión",
    skip: "Ir a la aplicación", 
    via_preorder: "preventa firmada por la llave de acceso del comprador (dinero de prueba)", via_funder: "dinero de un financiador, retenido para este hito", via_blink: "Acción de Solana (Blink)",
    hero_t: "Investigación que funciona, a la espera de un mercado.",
    hero_p: "Pega un artículo. Qloo muestra quién compraría su producto, dónde y a qué precio.",
    
    cross_t: "Iniciar un cruce", cross_ref: "Id del artículo (DOI, arXiv, PubMed, OpenAlex, patente)", cross_or: "o tu propia idea",
    cross_idea: "Describe la idea de producto", cross_place: "Mercado de lanzamiento (opcional)", cross_product: "Frase del producto (opcional)",
    cross_go: "Ejecutar el cruce", cross_busy: "El agente está cruzando",
    timeline_t: "El cruce, en vivo", open_product: "Abrir la página del producto",
    try: "Prueba:",
    buy_t: "Reservar", 
    buy_wallet: "Con tu monedero", buy_wallet_p: "Una Solana Action: cualquier monedero firma. Este servidor nunca guarda tu clave.",
    
    buy_btn: "Reservar con monedero", buy_demo_btn: "Reservar con mi llave de acceso", units: "Unidades",
    for_l: "Para", where_l: "Lanzamiento en", price_l: "Precio", goal_l: "Meta", unserved_l: "Público que el líder no atiende",
    fund_t: "Respaldar un hito", fund_p: "Tu dinero queda retenido hasta que la prueba se valida. El fabricante cobra solo con prueba.",
    
    contribute_t: "Trabajo abierto", contribute_p: "Únete a una ronda o haz un hito. El trabajo se juzga y luego se paga.",
    contribute_none: "No hay rondas abiertas en este servidor. Los hitos de abajo esperan pruebas.",
    make_t: "Hitos y pagos", make_p: "Publica una página pública con el id. Los árbitros la revisan; el dinero retenido se libera.",
    agents_t: "Para agentes", agents_p: "Los mismos flujos de cruce, reserva e hito por el Model Context Protocol.",
    agents_add: "Añade este servidor por URL en Claude, Cursor o cualquier cliente MCP:",
    verify_link: "Cómo verificamos", lang_l: "Idioma",
    test_money: "Dinero de prueba devnet: sin fondos reales", status_live: "Qloo: activo", status_off: "Qloo: inactivo",
    loading: "Trabajando", empty: "Nada aquí todavía", err_signin: "Inicia sesión primero.",
    receipt_t: "Retenido hasta la prueba", evidence_pin: "Huella de la prueba en cadena", page_sha: "sha256 de la página de prueba",
    milestone_prove: "Probar y liberar", evidence_url: "URL de la página de prueba", claim_id: "Id del reclamo",
    reserve: "Reserva", target: "Meta", released: "liberado", locked: "bloqueado", refuse: "Rechazado", open_v: "Reservas abiertas",
    cannot: "No decidible", footer: "Los datos de Qloo se leen solo en el servidor. Dinero retenido en Solana devnet con unidades de prueba: sin dinero real. Licencia MIT.",
    pk_new: "Crear un monedero passkey", pk_use: "Entrar con mi passkey",
    pk_note: "Sin frase semilla: la llave de acceso es tu billetera (una billetera inteligente LazorKit en devnet). Cada pago se aprueba en tu dispositivo.",
    
    mem_search: "Buscar en la memoria de Knos",
    wallet_t: "Tu billetera con llave de acceso", faucet_btn: "Obtener 25 unidades de prueba de devnet", claim_btn: "Yo lo fabrico: reclamar el hito con mi llave de acceso", claimed: "Llave de acceso del fabricante", pk_sign: "Aprueba con tu llave de acceso",
    
    
    
    home_own: "Cruza tu propio artículo",
    back_btn: "Apoyar",
    fundm_btn: "Financiar un hito",
    contrib_btn: "Contribuir",
    backed_l: "reservados",
    held_l: "retenidas para el hito",
    maker_wanted: "se busca fabricante",
    of: "de",
    checking: "Leyendo la demanda en vivo",
    open_project: "Abrir el proyecto",
    no_maker: "Aún no hay fabricante. Comprométete: pagas solo cuando esté hecho.",
    amc_btn: "Comprometerme a comprar",
    committed_l: "Comprometido",
    amc_rule: "se paga al fabricante solo al verificarse",
    name_l: "Tu nombre",
    pk_none: "Este navegador no admite llaves de acceso. Prueba un teléfono u otro navegador.",
    
    
    
    
    make_need: "Hitos que necesitan fabricante",
    make_btn: "Lo fabrico",
    open_ms: "hitos abiertos",
    attempt_l: "Tu intento",
    paid_passkey: "se paga en tu billetera de llave"
  },
  pt: {
    tag: "Pesquisa comprovada, produtos financiados",
    
    sign_in: "Entrar", sign_out: "Sair",
    skip: "Ir para o aplicativo", 
    via_preorder: "pré-venda assinada pela chave de acesso do comprador (dinheiro de teste)", via_funder: "dinheiro de um financiador, retido para este marco", via_blink: "Ação Solana (Blink)",
    hero_t: "Pesquisa que funciona, à espera de um mercado.",
    hero_p: "Cole um artigo. A Qloo mostra quem compraria o produto, onde e a que preço.",
    
    cross_t: "Iniciar uma travessia", cross_ref: "Id do artigo (DOI, arXiv, PubMed, OpenAlex, patente)", cross_or: "ou a sua própria ideia",
    cross_idea: "Descreva a ideia de produto", cross_place: "Mercado de lançamento (opcional)", cross_product: "Frase do produto (opcional)",
    cross_go: "Executar a travessia", cross_busy: "O agente está a atravessar",
    timeline_t: "A travessia, ao vivo", open_product: "Abrir a página do produto",
    try: "Experimente:",
    buy_t: "Pré-venda", 
    buy_wallet: "Com a sua carteira", buy_wallet_p: "Uma Solana Action: qualquer carteira assina. Este servidor nunca guarda a sua chave.",
    
    buy_btn: "Pré-comprar com carteira", buy_demo_btn: "Reservar com minha chave de acesso", units: "Unidades",
    for_l: "Para", where_l: "Lançamento em", price_l: "Preço", goal_l: "Meta", unserved_l: "Público que o líder não atende",
    fund_t: "Apoiar um marco", fund_p: "Seu dinheiro fica retido até a prova ser validada. O fabricante só recebe com prova.",
    
    contribute_t: "Trabalho aberto", contribute_p: "Entre numa rodada ou faça uma etapa. O trabalho é julgado e pago.",
    contribute_none: "Sem rodadas abertas neste servidor. Os marcos abaixo aguardam provas.",
    make_t: "Marcos e pagamentos", make_p: "Publique uma página pública com o id. Os árbitros conferem; o dinheiro retido é liberado.",
    agents_t: "Para agentes", agents_p: "Os mesmos fluxos de travessia, pré-venda e marco pelo Model Context Protocol.",
    agents_add: "Adicione este servidor por URL no Claude, Cursor ou qualquer cliente MCP:",
    verify_link: "Como verificamos", lang_l: "Idioma",
    test_money: "Dinheiro de teste devnet: sem fundos reais", status_live: "Qloo: ativo", status_off: "Qloo: inativo",
    loading: "A trabalhar", empty: "Nada aqui ainda", err_signin: "Entre primeiro.",
    receipt_t: "Retido até a prova", evidence_pin: "Selo da prova na cadeia", page_sha: "sha256 da página de prova",
    milestone_prove: "Provar e liberar", evidence_url: "URL da página de prova", claim_id: "Id da alegação",
    reserve: "Reserva", target: "Meta", released: "liberado", locked: "bloqueado", refuse: "Recusado", open_v: "Pré-vendas abertas",
    cannot: "Indecidível", footer: "Os dados da Qloo são lidos só no servidor. Dinheiro retido na Solana devnet com unidades de teste: sem dinheiro real. Licença MIT.",
    pk_new: "Criar carteira passkey", pk_use: "Entrar com a minha passkey",
    pk_note: "Sem frase-semente: a chave de acesso é sua carteira (uma carteira inteligente LazorKit na devnet). Cada pagamento é aprovado no seu dispositivo.",
    
    mem_search: "Pesquisar a memória do Knos",
    wallet_t: "Sua carteira de chave de acesso", faucet_btn: "Receber 25 unidades de teste da devnet", claim_btn: "Eu fabrico: reivindicar o marco com minha chave de acesso", claimed: "Chave de acesso do fabricante", pk_sign: "Aprove com sua chave de acesso",
    
    
    
    home_own: "Cruze seu próprio artigo",
    back_btn: "Apoiar",
    fundm_btn: "Financiar uma etapa",
    contrib_btn: "Contribuir",
    backed_l: "pré-encomendados",
    held_l: "retidas para a etapa",
    maker_wanted: "procura-se fabricante",
    of: "de",
    checking: "Lendo a demanda ao vivo",
    open_project: "Abrir o projeto",
    no_maker: "Ainda sem fabricante. Comprometa-se: você paga só quando for feito.",
    amc_btn: "Comprometer-me a comprar",
    committed_l: "Comprometido",
    amc_rule: "pago ao fabricante só após a verificação",
    name_l: "Seu nome",
    pk_none: "Este navegador não tem chaves de acesso. Tente um celular ou outro navegador.",
    
    
    
    
    make_need: "Etapas que precisam de fabricante",
    make_btn: "Eu faço",
    open_ms: "etapas abertas",
    attempt_l: "Sua tentativa",
    paid_passkey: "pago na sua carteira de chave"
  },
  ar: {
    tag: "بحث مثبت، منتجات ممولة",
    
    sign_in: "تسجيل الدخول", sign_out: "تسجيل الخروج",
    skip: "انتقل إلى التطبيق", 
    via_preorder: "طلب مسبق وقّعه مفتاح مرور المشتري (أموال اختبار)", via_funder: "أموال ممول، محجوزة لهذه المرحلة", via_blink: "إجراء Solana (Blink)",
    hero_t: "بحث ناجح ينتظر سوقًا.",
    hero_p: "الصق بحثًا. تُظهر Qloo من سيشتري منتجه وأين وبأي سعر.",
    
    cross_t: "ابدأ العبور", cross_ref: "معرّف الورقة (DOI أو arXiv أو PubMed أو OpenAlex أو براءة)", cross_or: "أو فكرتك الخاصة",
    cross_idea: "صف فكرة المنتج", cross_place: "سوق الإطلاق (اختياري)", cross_product: "صياغة المنتج (اختياري)",
    cross_go: "شغّل العبور", cross_busy: "الوكيل يعبر الآن",
    timeline_t: "العبور، مباشرةً", open_product: "افتح صفحة المنتج",
    try: "جرّب:",
    buy_t: "طلب مسبق", 
    buy_wallet: "بمحفظتك", buy_wallet_p: "عملية Solana Action: أي محفظة توقّع. هذا الخادم لا يحتفظ بمفتاحك أبدًا.",
    
    buy_btn: "اطلب مسبقًا بمحفظة", buy_demo_btn: "اطلب مسبقًا بمفتاح مروري", units: "وحدات",
    for_l: "لمن", where_l: "الإطلاق في", price_l: "السعر", goal_l: "هدف التمويل", unserved_l: "جمهور لا يخدمه الرائد",
    fund_t: "ادعم مرحلة", fund_p: "يبقى مالك محجوزًا حتى يُقبل الإثبات. يُدفع للصانع فقط بالإثبات.",
    
    contribute_t: "عمل مفتوح", contribute_p: "انضم إلى جولة أو اصنع مرحلة. يُقيَّم العمل ثم يُدفع.",
    contribute_none: "لا جولات مفتوحة على هذا الخادم الآن. المراحل أدناه تنتظر الإثبات.",
    make_t: "المراحل والمدفوعات", make_p: "انشر صفحة عامة بمعرّف المطالبة. يتحقق الحكام؛ ويُفرج عن المال المحجوز.",
    agents_t: "للوكلاء", agents_p: "التدفقات نفسها للعبور والطلب المسبق والمراحل عبر Model Context Protocol.",
    agents_add: "أضف هذا الخادم بالرابط في Claude أو Cursor أو أي عميل MCP:",
    verify_link: "كيف نتحقق", lang_l: "اللغة",
    test_money: "أموال اختبار devnet: لا أموال حقيقية", status_live: "Qloo: مباشر", status_off: "Qloo: متوقف",
    loading: "جارٍ العمل", empty: "لا شيء هنا بعد", err_signin: "سجّل الدخول أولًا.",
    receipt_t: "محجوز حتى الإثبات", evidence_pin: "بصمة الإثبات على السلسلة", page_sha: "sha256 لصفحة الإثبات",
    milestone_prove: "أثبت وحرّر", evidence_url: "رابط صفحة الإثبات", claim_id: "معرّف المطالبة",
    reserve: "الاحتياطي", target: "الهدف", released: "محرَّر", locked: "مقفول", refuse: "مرفوض", open_v: "الطلب المسبق مفتوح",
    cannot: "تعذّر القرار", footer: "تُقرأ بيانات Qloo على الخادم فقط. المال محجوز على Solana devnet بوحدات اختبار: لا أموال حقيقية. رخصة MIT.",
    pk_new: "أنشئ محفظة مفتاح مرور", pk_use: "ادخل بمفتاح المرور",
    pk_note: "بلا عبارة استرداد: مفتاح المرور هو محفظتك (محفظة LazorKit ذكية على devnet). كل دفعة تُعتمد على جهازك.",
    
    mem_search: "ابحث في كل ما يتذكره Knos",
    wallet_t: "محفظة مفتاح المرور", faucet_btn: "احصل على 25 وحدة اختبار devnet", claim_btn: "أنا الصانع: اطلب المرحلة بمفتاح مروري", claimed: "مفتاح مرور الصانع", pk_sign: "اعتمد بمفتاح مرورك",
    
    
    
    home_own: "اختبر بحثك الخاص",
    back_btn: "ادعمه",
    fundm_btn: "موّل مرحلة",
    contrib_btn: "ساهم",
    backed_l: "طُلبت مسبقًا",
    held_l: "محجوزة للمرحلة",
    maker_wanted: "مطلوب صانع",
    of: "من",
    checking: "جارٍ قراءة الطلب المباشر",
    open_project: "افتح المشروع",
    no_maker: "لا صانع بعد. التزم الآن: تدفع فقط عند صنعه.",
    amc_btn: "التزم بالشراء",
    committed_l: "تم الالتزام",
    amc_rule: "يُدفع للصانع فقط بعد التحقق",
    name_l: "اسمك",
    pk_none: "هذا المتصفح لا يدعم مفاتيح المرور. جرّب هاتفًا أو متصفحًا آخر.",
    
    
    
    
    make_need: "مراحل تحتاج صانعًا",
    make_btn: "سأصنعه",
    open_ms: "مراحل مفتوحة",
    attempt_l: "محاولتك",
    paid_passkey: "يُدفع إلى محفظة مفتاح المرور"
  },
  hi: {
    tag: "सिद्ध शोध, वित्त-पोषित उत्पाद",
    
    sign_in: "साइन इन", sign_out: "साइन आउट",
    skip: "ऐप पर जाएँ", 
    via_preorder: "खरीदार की पासकी से हस्ताक्षरित प्री-ऑर्डर (टेस्ट पैसा)", via_funder: "फ़ंडर का धन: इस मील-पत्थर के लिए रोका गया", via_blink: "Solana Action (Blink)",
    hero_t: "काम करने वाला शोध, बाज़ार की प्रतीक्षा में।",
    hero_p: "शोधपत्र चिपकाएँ। Qloo बताता है कि उत्पाद कौन, कहाँ और किस दाम पर खरीदेगा।",
    
    cross_t: "क्रॉसिंग शुरू करें", cross_ref: "पेपर id (DOI, arXiv, PubMed, OpenAlex, पेटेंट)", cross_or: "या अपना विचार",
    cross_idea: "उत्पाद का विचार लिखें", cross_place: "लॉन्च बाज़ार (वैकल्पिक)", cross_product: "उत्पाद वाक्यांश (वैकल्पिक)",
    cross_go: "क्रॉसिंग चलाएँ", cross_busy: "एजेंट पार कर रहा है",
    timeline_t: "क्रॉसिंग, लाइव", open_product: "उत्पाद पृष्ठ खोलें",
    try: "आज़माएँ:",
    buy_t: "प्री-ऑर्डर", 
    buy_wallet: "अपने वॉलेट से", buy_wallet_p: "एक Solana Action: कोई भी वॉलेट साइन करे। यह सर्वर आपकी कुंजी कभी नहीं रखता।",
    
    buy_btn: "वॉलेट से प्री-ऑर्डर", buy_demo_btn: "मेरी पासकी से प्री-ऑर्डर करें", units: "इकाइयाँ",
    for_l: "किसके लिए", where_l: "लॉन्च", price_l: "मूल्य", goal_l: "लक्ष्य", unserved_l: "जिन्हें अग्रणी नहीं पूरा करता",
    fund_t: "मील-पत्थर को समर्थन दें", fund_p: "सबूत पास होने तक आपका पैसा रोका रहता है। निर्माता को सबूत पर ही भुगतान।",
    
    contribute_t: "खुला काम", contribute_p: "राउंड में जुड़ें या पड़ाव बनाएँ। काम जाँचा जाता है, फिर भुगतान।",
    contribute_none: "इस सर्वर पर अभी कोई राउंड खुला नहीं। नीचे के मील-पत्थर प्रमाण की प्रतीक्षा में हैं।",
    make_t: "मील-पत्थर और भुगतान", make_p: "क्लेम आईडी के साथ सार्वजनिक पेज डालें। रेफ़री जाँचते हैं; रोका गया पैसा जारी होता है।",
    agents_t: "एजेंटों के लिए", agents_p: "वही क्रॉसिंग, प्री-ऑर्डर और मील-पत्थर प्रवाह Model Context Protocol से।",
    agents_add: "Claude, Cursor या किसी MCP क्लाइंट में URL से यह सर्वर जोड़ें:",
    verify_link: "हम कैसे सत्यापित करते हैं", lang_l: "भाषा",
    test_money: "Devnet परीक्षण धन: असली धन नहीं", status_live: "Qloo: लाइव", status_off: "Qloo: बंद",
    loading: "कार्य जारी", empty: "अभी यहाँ कुछ नहीं", err_signin: "पहले साइन इन करें।",
    receipt_t: "सबूत तक रोका गया", evidence_pin: "चेन पर प्रमाण-मुहर", page_sha: "प्रमाण पृष्ठ का sha256",
    milestone_prove: "सिद्ध करें और रिलीज़ करें", evidence_url: "प्रमाण पृष्ठ URL", claim_id: "Claim id",
    reserve: "आरक्षित", target: "लक्ष्य", released: "रिलीज़", locked: "लॉक", refuse: "अस्वीकृत", open_v: "प्री-ऑर्डर खुले",
    cannot: "निर्णय संभव नहीं", footer: "Qloo डेटा केवल सर्वर पर पढ़ा जाता है। पैसा Solana devnet पर परीक्षण इकाइयों में रोका जाता है: असली धन नहीं। MIT लाइसेंस।",
    pk_new: "Passkey वॉलेट बनाएँ", pk_use: "मेरी passkey से साइन इन",
    pk_note: "कोई सीड फ़्रेज़ नहीं: पासकी ही आपका वॉलेट है (devnet पर LazorKit स्मार्ट वॉलेट)। हर भुगतान आपके डिवाइस पर स्वीकृत होता है।",
    
    mem_search: "Knos की स्मृति में खोजें",
    wallet_t: "आपका पासकी वॉलेट", faucet_btn: "25 devnet टेस्ट यूनिट पाएँ", claim_btn: "मैं इसे बनाता हूँ: अपनी पासकी से मील-पत्थर का दावा करें", claimed: "निर्माता की पासकी", pk_sign: "अपनी पासकी से स्वीकृत करें",
    
    
    
    home_own: "अपना शोधपत्र जाँचें",
    back_btn: "समर्थन करें",
    fundm_btn: "पड़ाव को फंड करें",
    contrib_btn: "योगदान दें",
    backed_l: "पूर्व-ऑर्डर",
    held_l: "पड़ाव के लिए रोकी गई",
    maker_wanted: "निर्माता चाहिए",
    of: "/",
    checking: "लाइव मांग पढ़ी जा रही है",
    open_project: "प्रोजेक्ट खोलें",
    no_maker: "अभी कोई निर्माता नहीं। अभी वादा करें: बनने पर ही भुगतान।",
    amc_btn: "खरीदने का वादा करें",
    committed_l: "वादा दर्ज",
    amc_rule: "सत्यापन पर ही निर्माता को भुगतान",
    name_l: "आपका नाम",
    pk_none: "इस ब्राउज़र में पासकी नहीं है। फ़ोन या दूसरा ब्राउज़र आज़माएँ।",
    
    
    
    
    make_need: "पड़ाव जिन्हें निर्माता चाहिए",
    make_btn: "मैं बनाऊँगा",
    open_ms: "खुले पड़ाव",
    attempt_l: "आपका प्रयास",
    paid_passkey: "आपके पासकी वॉलेट में भुगतान"
  },
  zh: {
    tag: "经验证的研究，获资助的产品",
    
    sign_in: "登录", sign_out: "退出",
    skip: "跳到应用", 
    via_preorder: "由买家通行密钥签名的预订（测试资金）", via_funder: "出资人资金：为此里程碑暂存", via_blink: "Solana Action（Blink）",
    hero_t: "有效的研究，在等待一个市场。",
    hero_p: "粘贴一篇论文。Qloo 显示谁会买它的产品、在哪里、什么价格。",
    
    cross_t: "开始一次跨越", cross_ref: "论文编号（DOI、arXiv、PubMed、OpenAlex、专利）", cross_or: "或你自己的想法",
    cross_idea: "描述产品想法", cross_place: "上市市场（可选）", cross_product: "产品措辞（可选）",
    cross_go: "运行跨越", cross_busy: "智能体正在跨越",
    timeline_t: "跨越实况", open_product: "打开产品页",
    try: "试试：",
    buy_t: "预订", 
    buy_wallet: "用你的钱包", buy_wallet_p: "一个 Solana Action：任何钱包都可签名。本服务器从不保存你的私钥。",
    
    buy_btn: "用钱包预订", buy_demo_btn: "用我的通行密钥预订", units: "数量",
    for_l: "目标人群", where_l: "首发地", price_l: "价格", goal_l: "筹资目标", unserved_l: "领先者未覆盖的人群",
    fund_t: "支持一个里程碑", fund_p: "你的钱会暂存，直到证明通过。制造者只凭证明收款。",
    
    contribute_t: "开放的工作", contribute_p: "加入一轮或完成一个里程碑。工作先评判，再付款。",
    contribute_none: "此服务器暂无开放轮次。下方里程碑正等待证明。",
    make_t: "里程碑与付款", make_p: "发布含声明 id 的公开页面。裁判核查后，暂存的钱放款。",
    agents_t: "面向智能体", agents_p: "同样的跨越、预订与里程碑流程，通过 Model Context Protocol 提供。",
    agents_add: "在 Claude、Cursor 或任何 MCP 客户端中按 URL 添加此服务器：",
    verify_link: "我们如何验证", lang_l: "语言",
    test_money: "Devnet 测试资金：非真实资金", status_live: "Qloo：在线", status_off: "Qloo：离线",
    loading: "处理中", empty: "这里还没有内容", err_signin: "请先登录。",
    receipt_t: "暂存至证明通过", evidence_pin: "链上证据指纹", page_sha: "证据页 sha256",
    milestone_prove: "证明并释放", evidence_url: "证据页 URL", claim_id: "Claim id",
    reserve: "保底", target: "目标", released: "已释放", locked: "已锁定", refuse: "已拒绝", open_v: "预订开放",
    cannot: "无法判定", footer: "Qloo 数据仅在服务器端读取。资金暂存在 Solana devnet，使用测试单位：没有真实资金。MIT 许可。",
    pk_new: "创建通行密钥钱包", pk_use: "用我的通行密钥登录",
    pk_note: "无助记词：通行密钥就是你的钱包（devnet 上的 LazorKit 智能钱包）。每笔付款都在你的设备上批准。",
    
    mem_search: "搜索 Knos 记住的一切",
    wallet_t: "你的通行密钥钱包", faucet_btn: "领取 25 个 devnet 测试单位", claim_btn: "我来制造：用我的通行密钥认领这个里程碑", claimed: "制造者的通行密钥", pk_sign: "用你的通行密钥批准",
    
    
    
    home_own: "交叉你自己的论文",
    back_btn: "支持它",
    fundm_btn: "资助里程碑",
    contrib_btn: "贡献",
    backed_l: "已预订",
    held_l: "为里程碑暂存",
    maker_wanted: "寻找制造者",
    of: "/",
    checking: "正在读取实时需求",
    open_project: "打开项目",
    no_maker: "还没有制造者。现在承诺：做出来才付款。",
    amc_btn: "承诺购买",
    committed_l: "已承诺",
    amc_rule: "仅在验证后付给制造者",
    name_l: "你的名字",
    pk_none: "此浏览器不支持通行密钥。请换手机或其他浏览器。",
    
    
    
    
    make_need: "需要制造者的里程碑",
    make_btn: "我来做",
    open_ms: "个开放里程碑",
    attempt_l: "你的尝试",
    paid_passkey: "付到你的通行密钥钱包"
  }
};
