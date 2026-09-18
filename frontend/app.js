const questionInput =
    document.getElementById("questionInput");

const sendBtn =
    document.getElementById("sendBtn");

const micBtn =
    document.getElementById("micBtn");

const voiceLangBtn =
    document.getElementById("voiceLangBtn");

const voiceStatus =
    document.getElementById("voiceStatus");


const messages =
    document.getElementById("messages");

const welcomeScreen =
    document.getElementById("welcomeScreen");

const newChatBtn =
    document.getElementById("newChatBtn");
    const sourceCards =
    document.querySelectorAll(".source-card");

const cacheToggle =
    document.getElementById("cacheToggle");

const cacheState =
    document.getElementById("cacheState");

const modeToggle =
    document.getElementById("modeToggle");

const modeState =
    document.getElementById("modeState");

const clearCacheBtn =
    document.getElementById("clearCacheBtn");


const modeOptions = [
    "auto",
    "fast",
    "balanced"
];

let sidebarSettings =
    JSON.parse(
        localStorage.getItem("deno_sidebar_settings")
    ) || {
        sources: {
            wikipedia: true,
            arxiv: true,
            web: true,
        },
        cache: true,
        mode: "auto",
    };


/*
    TRUE:
    Backend olmadan frontend işləyəcək.

    FALSE:
    Real backend API istifadə olunacaq.
*/

const USE_MOCK = false;


/*
    Backend hazır olanda
    endpoint buradan dəyişdiriləcək.
*/

const API_URL = "https://deepnova-research-assistant.onrender.com/api/ask";

questionInput.addEventListener(
    "input",
    () => {

        questionInput.style.height =
            "auto";

        questionInput.style.height =
            questionInput.scrollHeight
            + "px";

    }
);


/*
    ENTER = send

    SHIFT + ENTER =
    new line
*/

questionInput.addEventListener(
    "keydown",
    (event) => {

        if (
            event.key === "Enter"
            &&
            !event.shiftKey
        ) {

            event.preventDefault();

            sendQuestion();

        }

    }
);


sendBtn.addEventListener(
    "click",
    sendQuestion
);


/*
    Suggested questions
*/

document
    .querySelectorAll(
        ".suggestion"
    )
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    questionInput.value =
                        button.dataset.question;

                    sendQuestion();

                }
            );

        }
    );


/*
    NEW CHAT
*/

newChatBtn.addEventListener(
    "click",
    () => {

        messages.innerHTML = "";

        welcomeScreen.style.display =
            "flex";

        questionInput.value = "";

        questionInput.focus();

    }
);


/*
    MAIN SEND FUNCTION
*/

async function sendQuestion() {

    const question =
        questionInput
            .value
            .trim();


    if (!question) {
        return;
    }
    
        /*
        ============================================
        TYPED "HEY DENO"
        ============================================
    */

    const typedWakeRegex =
        /^hey\s+(deno|dino|deeno)\b[,\s.!?-]*/i;


    if (typedWakeRegex.test(question)) {

        const remainingQuestion =
            question
                .replace(
                    typedWakeRegex,
                    ""
                )
                .trim();


        /*
            User only writes:
            "Hey DENO"
        */

        if (!remainingQuestion) {

            welcomeScreen.style.display =
                "none";

            addUserMessage(question);

            questionInput.value = "";

            questionInput.style.height =
                "auto";

            awaitingDenoQuestion = true;


            addAssistantMessage(
                "Hey! I'm listening 👋 What would you like to research?",
                []
            );


            /*
                DENO can also greet by voice
            */

            if (
                typeof denoSpeak
                === "function"
            ) {

                denoSpeak(
                    "Hey! I'm listening."
                );

            }

            return;
        }


        /*
            Example:
            "Hey DENO, explain machine learning"

            Remove "Hey DENO" and research
            the actual question.
        */

        questionInput.value =
            remainingQuestion;

        return sendQuestion();

    }


    welcomeScreen.style.display =
        "none";


    addUserMessage(question);


    questionInput.value = "";

    questionInput.style.height =
        "auto";


    sendBtn.disabled = true;


    const loadingElement =
        addLoadingMessage();


    try {

        const result =
            USE_MOCK
                ? await mockResearch(question)
                : await askBackend(question);


        loadingElement.remove();


        addAssistantMessage(
            result.answer,
            result.sources
        );

    }

    catch (error) {

        console.error(error);


        loadingElement.remove();


        addAssistantMessage(
            "Something went wrong while processing your research request.",
            []
        );

    }

    finally {

        sendBtn.disabled = false;

        scrollToBottom();

    }

}


/*
    USER MESSAGE
*/

function addUserMessage(text) {

    const message =
        document.createElement("div");


    message.className =
        "message user";


    const content =
        document.createElement("div");


    content.className =
        "message-content";


    content.textContent =
        text;


    message.appendChild(content);


    messages.appendChild(message);


    scrollToBottom();

}


/*
    AI MESSAGE
*/

function addAssistantMessage(
    answer,
    sources = []
) {

    const message =
        document.createElement("div");


    message.className =
        "message assistant";


    const wrapper =
        document.createElement("div");


    wrapper.className =
        "assistant-wrapper";


    const header =
        document.createElement("div");


    header.className =
        "assistant-header";


    header.innerHTML = `
        <div class="ai-icon">
            ✦
        </div>

        Research Assistant
    `;


    const content =
        document.createElement("div");


    content.className =
        "message-content";


    const answerElement =
        document.createElement("div");


    answerElement.textContent =
        answer;


    content.appendChild(
        answerElement
    );


    /*
        SOURCES
    */

    if (
        sources
        &&
        sources.length > 0
    ) {

        const sourceContainer =
            document.createElement(
                "div"
            );


        sourceContainer.className =
            "sources";


        const title =
            document.createElement(
                "div"
            );


        title.className =
            "sources-title";


        title.textContent =
            "Sources";


        sourceContainer.appendChild(
            title
        );


        sources.forEach(
            source => {

                const sourceRow =
                    document.createElement(
                        "div"
                    );


                sourceRow.className =
                    "source";


                sourceRow.innerHTML =
                    "↗";


                const link =
                    document.createElement(
                        "a"
                    );


                link.textContent =
                    source.title;


                link.href =
                    source.url || "#";


                link.target =
                    "_blank";


                link.rel =
                    "noopener noreferrer";


                sourceRow.appendChild(
                    link
                );


                sourceContainer.appendChild(
                    sourceRow
                );

            }
        );


        content.appendChild(
            sourceContainer
        );

    }


    wrapper.appendChild(
        header
    );


    wrapper.appendChild(
        content
    );


    message.appendChild(
        wrapper
    );


    messages.appendChild(
        message
    );


    scrollToBottom();

}


/*
    LOADING MESSAGE
*/

function addLoadingMessage() {

    const message =
        document.createElement("div");


    message.className =
        "message assistant";


    message.innerHTML = `

        <div class="assistant-wrapper">

            <div class="assistant-header">

                <div class="ai-icon">
                    ✦
                </div>

                Researching sources...

            </div>

            <div class="message-content">

                <div class="typing">

                    <span></span>
                    <span></span>
                    <span></span>

                </div>

            </div>

        </div>

    `;


    messages.appendChild(
        message
    );


    scrollToBottom();


    return message;

}


/*
    TEMPORARY MOCK BACKEND

    Backend hələ işləmədiyi üçün
    frontend test etmək üçündür.
*/

async function mockResearch(question) {

    await new Promise(
        resolve =>
            setTimeout(
                resolve,
                1400
            )
    );


    return {

        answer:
            `This is a demonstration research response for: "${question}"

The frontend is currently running in mock mode. Once the Python research backend is connected, this response will be replaced with real information collected from academic, web and AI sources.`,

        sources: [

            {
                title:
                    "Wikipedia",

                url:
                    "https://www.wikipedia.org/"
            },

            {
                title:
                    "arXiv",

                url:
                    "https://arxiv.org/"
            },

            {
                title:
                    "Research Web Source",

                url:
                    "https://example.com/"
            }

        ]

    };

}


/*
    REAL BACKEND

    Backend düzələndən sonra
    USE_MOCK = false edəcəyik.
*/

async function askBackend(question) {
    const activeSources =
        getActiveSources();

    const response =
        await fetch(
            API_URL,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    question: question,
                    sources: activeSources,
                    cache: sidebarSettings.cache,
                    mode: sidebarSettings.mode
                })
            }
        );

    if (!response.ok) {
        const errorText =
            await response.text();

        throw new Error(
            "Backend request failed: "
            + response.status
            + " "
            + errorText
        );
    }

    return await response.json();
}

/*
    AUTO SCROLL
*/

function scrollToBottom() {

    const chat =
        document.getElementById(
            "chatContainer"
        );


    chat.scrollTo(
        {
            top:
                chat.scrollHeight,

            behavior:
                "smooth"
        }
    );

}

function saveSidebarSettings() {
    localStorage.setItem(
        "deno_sidebar_settings",
        JSON.stringify(sidebarSettings)
    );
}

function renderSidebarSettings() {
    sourceCards.forEach(card => {
        const source = card.dataset.source;
        const enabled =
            sidebarSettings.sources[source];

        if (enabled) {
            card.classList.add("active");
        } else {
            card.classList.remove("active");
        }
    });

    cacheState.textContent =
        sidebarSettings.cache ? "on" : "off";

    modeState.textContent =
        sidebarSettings.mode;
}

function getActiveSources() {
    return Object.entries(
        sidebarSettings.sources
    )
        .filter(([_, enabled]) => enabled)
        .map(([name]) => name);
}


sourceCards.forEach(card => {
    card.addEventListener("click", () => {
        const source = card.dataset.source;

        sidebarSettings.sources[source] =
            !sidebarSettings.sources[source];

        const activeSources =
            getActiveSources();

        if (activeSources.length === 0) {
            sidebarSettings.sources[source] = true;
            alert("At least one source must stay enabled.");
            return;
        }

        saveSidebarSettings();
        renderSidebarSettings();
    });
});

cacheToggle.addEventListener("click", () => {
    sidebarSettings.cache =
        !sidebarSettings.cache;

    saveSidebarSettings();
    renderSidebarSettings();
});

modeToggle.addEventListener("click", () => {
    const currentIndex =
        modeOptions.indexOf(
            sidebarSettings.mode
        );

    const nextIndex =
        (currentIndex + 1) % modeOptions.length;

    sidebarSettings.mode =
        modeOptions[nextIndex];

    saveSidebarSettings();
    renderSidebarSettings();
});

clearCacheBtn.addEventListener(
    "click",
    async () => {
        try {
            const response = await fetch(
                "http://127.0.0.1:8000/api/cache/clear",
                {
                    method: "POST",
                }
            );

            const result =
                await response.json();

            alert(
                `Cache cleared. Removed: ${result.removed}`
            );
        } catch (error) {
            console.error(error);
            alert("Could not clear cache.");
        }
    }
);

renderSidebarSettings();


/*
    ============================================
    DENO VOICE ASSISTANT
    ============================================
*/

const SpeechRecognition =
    window.SpeechRecognition
    || window.webkitSpeechRecognition;


let recognition = null;

let voiceEnabled = false;

let awaitingDenoQuestion = false;

let restartingRecognition = false;

const voiceLanguages = {
    EN: "en-US",
    AZ: "az-AZ",
    TR: "tr-TR"
};

const voiceLanguageOrder = [
    "EN",
    "AZ",
    "TR"
];

let currentVoiceLanguage =
    localStorage.getItem(
        "deno_voice_language"
    ) || "EN";


/*
    Speak a short DENO response
*/

function denoSpeak(text) {

    if (!("speechSynthesis" in window)) {
        return;
    }

    window.speechSynthesis.cancel();

    const utterance =
        new SpeechSynthesisUtterance(text);

    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.volume = 1;


    /*
        Stop recognition while DENO itself
        is speaking, otherwise DENO may hear
        its own voice.
    */

    if (
        recognition
        &&
        voiceEnabled
    ) {

        restartingRecognition = true;

        try {
            recognition.stop();
        } catch (error) {
            console.log(error);
        }

    }


    utterance.onend = () => {

        restartingRecognition = false;

        if (voiceEnabled) {

            setTimeout(
                startVoiceRecognition,
                350
            );

        }

    };


    window.speechSynthesis.speak(
        utterance
    );

}


/*
    Send recognised voice question
*/

function submitVoiceQuestion(question) {

    const cleanQuestion =
        question.trim();

    if (!cleanQuestion) {
        return;
    }


    questionInput.value =
        cleanQuestion;


    /*
        Resize textarea like normal typing
    */

    questionInput.style.height =
        "auto";

    questionInput.style.height =
        questionInput.scrollHeight
        + "px";


    voiceStatus.textContent =
        "Researching your question...";

    voiceStatus.classList.remove(
        "awake"
    );


    /*
        Uses your EXISTING sendQuestion()
    */

    sendQuestion();

}


/*
    Process recognised speech
*/

function handleVoiceTranscript(
    transcript
) {

    const original =
        transcript.trim();

    const lower =
        original.toLowerCase();


    console.log(
        "DENO heard:",
        original
    );


    /*
        Speech engines sometimes hear
        DENO as Dino.
    */

    const wakeRegex =
        /\bhey\s+(deno|dino|deeno)\b/i;


    /*
        HEY DENO detected
    */

    if (wakeRegex.test(original)) {

    const remaining =
        original
            .replace(
                wakeRegex,
                ""
            )
            .replace(
                /^[,\s.!?-]+/,
                ""
            )
            .trim();


    /*
        ============================================
        "HEY DENO" + QUESTION
        ============================================

        Example:
        "Hey DENO explain machine learning"

        Greeting göstərmirik.
        Birbaşa research başlayır.
    */

    if (remaining) {

        awaitingDenoQuestion =
            false;

        voiceStatus.textContent =
            "Got it. Researching...";

        voiceStatus.classList.remove(
            "awake"
        );

        submitVoiceQuestion(
            remaining
        );

        return;
    }


    /*
        ============================================
        ONLY "HEY DENO"
        ============================================

        Example:
        "Hey DENO"

        Chat-da greeting göstəririk
        və növbəti sualı gözləyirik.
    */

    awaitingDenoQuestion =
        true;

    welcomeScreen.style.display =
        "none";


    /*
        Show spoken Hey DENO
        as user message
    */

    addUserMessage(
        "Hey DENO"
    );


    /*
        Show DENO greeting
        in chat
    */

    addAssistantMessage(
        "Hey! I'm listening 👋 What would you like to research?",
        []
    );


    voiceStatus.textContent =
        "DENO is listening...";

    voiceStatus.classList.add(
        "awake"
    );


    /*
        Voice greeting
    */

    denoSpeak(
        "Hey! I'm listening."
    );

    return;
}


    /*
        User previously said:
        Hey DENO

        This next sentence becomes
        the question.
    */

    if (awaitingDenoQuestion) {

        awaitingDenoQuestion =
            false;

        /*
            Hey DENO-dan sonra deyilən sualı
            avtomatik göndərmirik.

            Input-a yazırıq ki,
            user əvvəlcə yoxlaya bilsin.
        */

        questionInput.value =
            original;

        questionInput.style.height =
            "auto";

        questionInput.style.height =
            questionInput.scrollHeight
            + "px";

        voiceStatus.textContent =
            "Question captured — review it and press Send.";

        voiceStatus.classList.remove(
            "awake"
        );

        questionInput.focus();

        return;
    }


    /*
        Normal microphone use:
        put speech into the input.

        It does NOT automatically send.
    */

    questionInput.value =
        original;


    questionInput.style.height =
        "auto";

    questionInput.style.height =
        questionInput.scrollHeight
        + "px";


    voiceStatus.textContent =
        "Voice captured — press send or say “Hey DENO”.";

}


/*
    Start recognition
*/

function startVoiceRecognition() {

    if (
        !recognition
        ||
        !voiceEnabled
    ) {
        return;
    }


    try {

        recognition.start();

    }

    catch (error) {

        /*
            start() may throw if it is
            already running.
        */

        console.log(
            "Recognition already active."
        );

    }

}


/*
    Initialize Web Speech API
*/

if (!SpeechRecognition) {

    micBtn.disabled = true;

    micBtn.title =
        "Voice recognition is not supported in this browser.";

    voiceStatus.textContent =
        "Voice recognition is not supported by this browser.";

}

else {

    recognition =
    new SpeechRecognition();

    recognition.lang =
        voiceLanguages[
            currentVoiceLanguage
        ];

    voiceLangBtn.textContent =
        currentVoiceLanguage;


    /*
        Keep listening while voice mode is ON
    */

    recognition.continuous = true;

    recognition.interimResults = false;


    /*
        Let browser use its preferred
        recognition language.

        We can add an AZ / EN selector later.
    */

    recognition.maxAlternatives = 1;


    recognition.onstart = () => {

        micBtn.classList.add(
            "listening"
        );

        voiceStatus.classList.add(
            "active"
        );


        if (!awaitingDenoQuestion) {

            voiceStatus.textContent =
                'Listening... Say “Hey DENO” or speak your question.';

        }

    };


    recognition.onresult = event => {

        const result =
            event.results[
                event.results.length - 1
            ];


        if (!result.isFinal) {
            return;
        }


        const transcript =
            result[0].transcript;


        handleVoiceTranscript(
            transcript
        );

    };


    recognition.onerror = event => {

        console.error(
            "Speech recognition error:",
            event.error
        );


        if (
            event.error
            === "not-allowed"
        ) {

            voiceEnabled = false;

            micBtn.classList.remove(
                "listening"
            );

            voiceStatus.textContent =
                "Microphone permission was denied.";

            return;
        }


        if (
            event.error
            === "no-speech"
        ) {

            voiceStatus.textContent =
                'Listening... Say “Hey DENO”.';

        }

    };


    recognition.onend = () => {

        micBtn.classList.remove(
            "listening"
        );


        /*
            Browser often stops speech
            recognition by itself.

            Restart it while voice mode
            remains enabled.
        */

        if (
            voiceEnabled
            &&
            !restartingRecognition
        ) {

            setTimeout(
                startVoiceRecognition,
                300
            );

        }

    };


    /*
        Microphone button

        ON  = continuous DENO listening
        OFF = stop microphone
    */

    micBtn.addEventListener(
        "click",
        () => {

            voiceEnabled =
                !voiceEnabled;


            if (voiceEnabled) {

                voiceStatus.textContent =
                    'Listening... Say “Hey DENO”.';

                startVoiceRecognition();

            }

            else {

                awaitingDenoQuestion =
                    false;

                micBtn.classList.remove(
                    "listening"
                );

                voiceStatus.classList.remove(
                    "active",
                    "awake"
                );

                voiceStatus.textContent =
                    'Say “Hey DENO” or tap the microphone';


                try {
                    recognition.stop();
                } catch (error) {
                    console.log(error);
                }

            }

        }
    );

}


voiceLangBtn.addEventListener(
    "click",
    () => {

        const currentIndex =
            voiceLanguageOrder.indexOf(
                currentVoiceLanguage
            );

        const nextIndex =
            (
                currentIndex + 1
            )
            % voiceLanguageOrder.length;

        currentVoiceLanguage =
            voiceLanguageOrder[
                nextIndex
            ];

        localStorage.setItem(
            "deno_voice_language",
            currentVoiceLanguage
        );

        voiceLangBtn.textContent =
            currentVoiceLanguage;

        recognition.lang =
            voiceLanguages[
                currentVoiceLanguage
            ];


        /*
            Recognition aktivdirsə,
            yeni dili tətbiq etmək üçün
            restart edirik.
        */

        if (
            voiceEnabled
            &&
            recognition
        ) {

            restartingRecognition =
                true;

            try {
                recognition.stop();
            }
            catch (error) {
                console.log(error);
            }


            setTimeout(
                () => {

                    restartingRecognition =
                        false;

                    startVoiceRecognition();

                },
                350
            );

        }


        voiceStatus.textContent =
            `Voice language: ${currentVoiceLanguage}`;

    }
);