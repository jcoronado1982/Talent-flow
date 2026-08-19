/** @vitest-environment jsdom */
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import { expect, test, vi, beforeEach } from 'vitest';
import Page from './+page.svelte';
import '@testing-library/jest-dom';

// We need to mock fetch globally
global.fetch = vi.fn();

let lastEventSource;

beforeEach(() => {
    vi.clearAllMocks();
    
    // Default mock implementation for fetch
    fetch.mockImplementation((url) => {
        if (url.includes('/status.json')) return Promise.resolve({ json: () => Promise.resolve({ status: 'Ready', logs: [] }) });
        if (url.includes('/api/stats')) return Promise.resolve({ json: () => Promise.resolve({ total_matches: 0, recent_matches: [] }) });
        if (url.includes('/check_interaction')) return Promise.resolve({ json: () => Promise.resolve({ status: 'none', question: '' }) });
        return Promise.resolve({ json: () => Promise.resolve({}) });
    });

    // Mock EventSource for SSE
    global.EventSource = class {
        constructor() {
            this.onmessage = null;
            this.onerror = null;
            this.close = vi.fn();
            this.addEventListener = vi.fn();
            this.removeEventListener = vi.fn();
            lastEventSource = this;
        }
    };
});

test('Iniciar Búsqueda trigger /search POST request', async () => {
    const { getByText } = render(Page);
    
    const startButton = getByText(/Iniciar Búsqueda/i);
    expect(startButton).toBeInTheDocument();

    await fireEvent.click(startButton);

    expect(fetch).toHaveBeenCalledWith('/search', expect.objectContaining({ method: 'POST' }));
});

test('Detener Búsqueda trigger /stop POST request', async () => {
    // Render the page
    const { getByText } = render(Page);
    
    // Simulate SSE message that sets status to Running
    lastEventSource.onmessage({ 
        data: JSON.stringify({ 
            status: { status: 'Running', logs: [] },
            stats: { total_matches: 0, recent_matches: [] }
        }) 
    });

    // Wait for the stop button
    await waitFor(() => {
        expect(getByText(/Detener Búsqueda/i)).toBeInTheDocument();
    });

    const stopButton = getByText(/Detener Búsqueda/i);
    await fireEvent.click(stopButton);

    expect(fetch).toHaveBeenCalledWith('/stop', expect.objectContaining({ method: 'POST' }));
});

test('Auto Aplicar trigger /apply POST request', async () => {
    const { getByText } = render(Page);
    
    const applyButton = getByText(/Auto Aplicar/i);
    expect(applyButton).toBeInTheDocument();

    await fireEvent.click(applyButton);

    expect(fetch).toHaveBeenCalledWith('/apply', expect.objectContaining({ method: 'POST' }));
});

test('InteractionModal handleAnswer trigger /submit_answer POST request', async () => {
    // Initial state with interaction mocked via fetch (checkInteraction uses fetch)
    fetch.mockImplementation((url) => {
        if (url.includes('/check_interaction')) return Promise.resolve({ json: () => Promise.resolve({ status: 'waiting_for_user', question: '¿Continuar?' }) });
        return Promise.resolve({ json: () => Promise.resolve({}) });
    });

    const { getByText, getByPlaceholderText } = render(Page);

    // Wait for modal to appear
    await waitFor(() => {
        expect(getByText(/¿Continuar?/i)).toBeInTheDocument();
    });

    const input = getByPlaceholderText(/Escribe la respuesta correcta aquí/i);
    const sendButton = getByText(/Enviar Respuesta/i);

    await fireEvent.input(input, { target: { value: 'Sí' } });
    await fireEvent.click(sendButton);

    expect(fetch).toHaveBeenCalledWith('/submit_answer', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ answer: 'Sí' })
    }));
});

test('UI updates with status and stats via SSE', async () => {
    const { getByText } = render(Page);

    // Simulate SSE message
    lastEventSource.onmessage({ 
        data: JSON.stringify({ 
            status: { 
                status: 'Running', 
                current_role: 'Software Engineer',
                current_location: 'Remote',
                total_combinations: 100,
                current_combination_index: 50,
                logs: ['Test Log Entry']
            },
            stats: { 
                total_matches: 42, 
                recent_matches: [{ id: 1, role: 'Job 1', company: 'Comp A', location: 'Loc A', match_score: 95, url: '#' }] 
            }
        }) 
    });

    await waitFor(() => {
        expect(getByText(/Software Engineer/i)).toBeInTheDocument();
        expect(getByText(/Remote/i)).toBeInTheDocument();
        expect(getByText(/42/i)).toBeInTheDocument();
        expect(getByText(/Job 1/i)).toBeInTheDocument();
        expect(getByText(/Test Log Entry/i)).toBeInTheDocument();
    });
});
