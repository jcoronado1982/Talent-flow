<script>
    let { show = false, question = '', onAnswer } = $props();
    let answer = $state('');

    function handleSubmit() {
        if (!answer) return alert("Por favor escribe una respuesta.");
        onAnswer(answer);
        answer = '';
    }
</script>

{#if show}
<div class="fixed inset-0 bg-black/80 flex justify-center items-center z-[1000] backdrop-blur-sm">
    <div class="bg-card-bg p-7 rounded-xl max-w-[500px] w-[90%] border-2 border-accent shadow-[0_0_20px_rgba(230,126,34,0.3)]">
        <h2 class="mt-0 text-accent font-bold text-2xl mb-4">⚠️ Ayuda Requerida</h2>
        <div class="text-lg mb-6 font-bold text-gray-100">{question}</div>
        
        <label class="block mb-2 text-gray-400 text-sm">Tu Respuesta:</label>
        <textarea 
            bind:value={answer}
            class="w-full p-3 mb-6 bg-gray-800 border border-gray-700 text-white rounded-lg focus:ring-2 focus:ring-accent outline-none"
            rows="3"
            placeholder="Escribe la respuesta correcta aquí..."
        ></textarea>
        
        <div class="flex justify-end gap-3">
            <button 
                onclick={handleSubmit}
                class="bg-primary text-white font-bold py-2 px-6 rounded-lg hover:bg-purple-700 transition-colors"
            >
                Enviar Respuesta
            </button>
        </div>
    </div>
</div>
{/if}
