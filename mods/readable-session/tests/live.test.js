import { describe, expect, mock, test } from 'claude-code/testing';
const BAND = {
    hasSurvey: false,
    isWorking: true,
    maxRows: 10,
    bodyColumns: 100,
    scroll: { bodyRows: 10, offset: 0 },
    view: {},
};
/** Stands for the engine's own drawing beneath the plugin. */
function answerRender(on) {
    on('ui.render', async (_$, e) => {
        const { Text } = _$.ui.resolve(e);
        return <Text>ENGINE</Text>;
    });
}
/** Tool calls the test never answers, so they stay running. */
function hangCalls(on) {
    on('tool.call', () => new Promise(() => { }));
}
async function band($, surface = 'terminal', props = BAND) {
    return $.ui.mount({ plugin: 'readable-session', surface, component: 'AbovePrompt', props });
}
describe('now band', () => {
    test('one row per running call: play icon, verb, detail', async ($, on) => {
        const clock = mock.clock(on);
        hangCalls(on);
        void $.tool.call({ tool: 'Bash', command: 'npm test\nnpm run lint', tool_use_id: 'u1' });
        void $.tool.call({ tool: 'mcp__claude_ai_Gmail__search_threads', query: 'x', tool_use_id: 'u2' });
        await clock.settle();
        const ui = await band($);
        const rows = (await ui.findAll({ type: 'Text' })).filter((t) => t.props.wrap === 'truncate-end');
        expect(rows).toHaveLength(2);
        expect(rows[0]?.text).toContain('Running Bash  npm test …');
        expect(rows[0]?.text).not.toContain('now');
        expect(rows[1]?.text).toContain('Using Gmail · search threads');
    });
    test('respects maxRows with a +N more row', async ($, on) => {
        const clock = mock.clock(on);
        hangCalls(on);
        for (const id of ['u1', 'u2', 'u3'])
            void $.tool.call({ tool: 'Read', file_path: `/a/${id}.ts`, tool_use_id: id });
        await clock.settle();
        const ui = await band($, 'terminal', { ...BAND, maxRows: 2 });
        const rows = (await ui.findAll({ type: 'Text' })).filter((t) => t.props.wrap === 'truncate-end');
        expect(rows).toHaveLength(2);
        expect(rows[0]?.text).toContain('Reading');
        expect(rows[1]?.text).toBe('+2 more');
    });
    test('a call at the permission prompt says it waits for you', async ($, on) => {
        const clock = mock.clock(on);
        let release = () => { };
        on('tool.call', async () => {
            await new Promise(r => (release = r));
            return { result: { stdout: '' } };
        });
        on('tool.check', async () => ({ decision: 'ask' }));
        const call = $.tool.call({ tool: 'PowerShell', command: 'Remove-Item x', tool_use_id: 'u1' });
        await clock.settle();
        const ui = await band($);
        expect((await ui.find({ text: /Running PowerShell/ }))?.text ?? '').toContain('Remove-Item x');
        await $.tool.check({ tool: 'PowerShell', input: { command: 'Remove-Item x' }, tool_use_id: 'u1' });
        const row = (await ui.find({ text: /waiting for you/ }))?.text ?? '';
        expect(row).toContain('waiting for you');
        expect(row).toContain('Remove-Item x');
        expect(row).not.toContain('Running');
        release();
        await call;
    });
    test('an allowed call keeps its verb', async ($, on) => {
        const clock = mock.clock(on);
        hangCalls(on);
        on('tool.check', async () => ({ decision: 'allow' }));
        void $.tool.call({ tool: 'Bash', command: 'ls', tool_use_id: 'u1' });
        await clock.settle();
        await $.tool.check({ tool: 'Bash', input: { command: 'ls' }, tool_use_id: 'u1' });
        const ui = await band($);
        expect(await ui.find({ text: /waiting for you/ })).toBe(undefined);
        expect(await ui.find({ text: /Running Bash/ })).not.toBe(undefined);
    });
    test('main-loop calls left over are pruned when the turn ends', async ($, on) => {
        const clock = mock.clock(on);
        answerRender(on);
        hangCalls(on);
        on('turn.start', async () => ({ turnId: 'T1' }));
        on('turn.complete', async () => ({ text: '' }));
        await $.turn.start({ text: 'hi', turnId: 'T1' });
        void $.tool.call({ tool: 'Bash', command: 'sleep 100', tool_use_id: 'u2' });
        await clock.settle();
        const before = await band($);
        expect(await before.find({ text: /Running Bash/ })).not.toBe(undefined);
        await before.unmount();
        await $.turn.complete({ answer: '', durationMs: 1, isAborted: true, turnId: 'T1', reason: 'aborted' });
        const after = await band($);
        expect(await after.find({ text: /Running Bash/ })).toBe(undefined);
    });
    test("a subagent's turn.complete prunes only its own calls", async ($, on) => {
        const clock = mock.clock(on);
        hangCalls(on);
        on('turn.complete', async () => ({ text: '' }));
        void $.tool.call({ tool: 'Grep', pattern: 'mine', tool_use_id: 'u1', agentId: 'a1' });
        void $.tool.call({ tool: 'Glob', pattern: '*.md', tool_use_id: 'u2', agentId: 'a2' });
        await clock.settle();
        await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 'T-a1', agentId: 'a1', reason: 'answer' });
        const ui = await band($);
        expect(await ui.find({ text: /Searching code/ })).toBe(undefined);
        expect(await ui.find({ text: /Finding files/ })).not.toBe(undefined);
    });
    test('draws nothing of its own on desktop', async ($, on) => {
        const clock = mock.clock(on);
        answerRender(on);
        hangCalls(on);
        void $.tool.call({ tool: 'Bash', command: 'ls', tool_use_id: 'u1' });
        await clock.settle();
        const ui = await band($, 'desktop');
        expect(await ui.find({ text: /Running Bash/ })).toBe(undefined);
        expect((await ui.find({ text: /ENGINE/ }))?.text).toBe('ENGINE');
    });
});
describe('spinner', () => {
    test('is left to the engine', async ($, on) => {
        answerRender(on);
        const ui = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'terminal',
            component: 'Spinner',
            props: { word: 'Sauteing', message: null, suffix: '…', mode: 'thinking' },
        });
        expect((await ui.find({ text: /ENGINE/ }))?.text).toBe('ENGINE');
    });
});
