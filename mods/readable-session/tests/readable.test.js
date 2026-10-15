import { describe, expect, test } from 'claude-code/testing';
import { brief, describeTool } from '../hooks/register.tsx';
describe('describeTool', () => {
    test('names the kind of work in plain words', () => {
        expect(describeTool('Bash', { command: 'git status --short\necho hi' })).toMatchObject({
            verb: 'Running Bash',
            past: 'Ran Bash',
            detail: 'git status --short …',
        });
        expect(describeTool('Bash', { command: 'ls\n\n' }).detail).toBe('ls');
        expect(describeTool('PowerShell', { command: 'Get-Process' })).toMatchObject({
            verb: 'Running PowerShell',
            past: 'Ran PowerShell',
        });
        expect(describeTool('Write', { file_path: 'C:\\dev\\app\\src\\server.ts' })).toMatchObject({
            verb: 'Writing',
            past: 'Wrote',
            detail: 'src/server.ts · TypeScript',
        });
        expect(describeTool('Edit', { file_path: '/repo/statusline.py' })).toMatchObject({
            past: 'Edited',
            detail: 'repo/statusline.py · Python',
        });
        expect(describeTool('Read', { file_path: 'main.py' })).toMatchObject({ past: 'Read', detail: 'main.py · Python' });
        expect(describeTool('WebSearch', { query: 'claude code statusline' })).toMatchObject({
            verb: 'Searching the web',
            past: 'Searched the web',
            detail: '"claude code statusline"',
        });
        expect(describeTool('Grep', { pattern: 'x' }).past).toBe('Searched code');
        expect(describeTool('Glob', { pattern: '*.ts' }).past).toBe('Found files');
        expect(describeTool('WebFetch', { url: 'https://a.dev' }).past).toBe('Fetched');
        expect(describeTool('Skill', { skill: 'tdd' }).past).toBe('Used skill');
        expect(describeTool('mcp__claude_ai_Gmail__search_threads', {})).toMatchObject({
            verb: 'Using Gmail',
            past: 'Used Gmail',
            detail: 'search threads',
            sep: ' · ',
        });
    });
    test('keeps only short input fields for the running list', () => {
        expect(brief({ file_path: 'a.ts', content: 'x'.repeat(10000) })).toEqual({ file_path: 'a.ts' });
    });
});
describe('drawing on terminal', () => {
    test('your prompt is a compact labeled card', async ($) => {
        const ui = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'terminal',
            component: 'UserMessage',
            props: { text: 'make my prompts visible', origin: { kind: 'composer' }, isExpanded: true },
        });
        const card = await ui.find({ type: 'Box' });
        expect(card?.text ?? '').toContain('You prompted');
        expect(card?.text ?? '').toContain('make my prompts visible');
        expect(card?.props.borderColor).toBe('claude');
        expect(card?.props.marginY).toBe(undefined);
    });
    test('a command row is a bordered card headed by the command and its arguments', async ($, on) => {
        on('ui.render', async (_$, e) => {
            const { Text } = _$.ui.resolve(e);
            return <Text>{e.props.text}</Text>;
        });
        const ui = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'terminal',
            component: 'CommandOutput',
            props: { command: 'effort', args: 'high', text: 'Effort set to high', isErrored: false },
        });
        const card = await ui.find({ type: 'Box' });
        expect(card?.props.borderColor).toBe('claude');
        expect(card?.props.borderStyle).toBe('round');
        expect(card?.text ?? '').toContain('/effort high');
        expect(card?.text ?? '').toContain('Effort set to high');
    });
    test('a command without arguments shows just the command; a failed one has a red border', async ($, on) => {
        on('ui.render', async (_$, e) => {
            const { Text } = _$.ui.resolve(e);
            return <Text>{e.props.text}</Text>;
        });
        const ok = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'terminal',
            component: 'CommandOutput',
            props: { command: 'context', args: '', text: 'x', isErrored: false },
        });
        expect((await ok.find({ type: 'Box' }))?.text ?? '').toContain('/context');
        expect((await ok.find({ type: 'Box' }))?.text ?? '').not.toContain('/context ');
        const bad = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'terminal',
            component: 'CommandOutput',
            props: { command: 'effort', args: 'bogus', text: 'Unknown effort', isErrored: true },
        });
        expect((await bad.find({ type: 'Box' }))?.props.borderColor).toBe('error');
    });
    test('a running tool row says what it does; a finished one, what it did', async ($) => {
        const props = {
            tool_use_id: 't1',
            tool: 'Write',
            input: { file_path: 'C:/dev/app/main.py', content: 'print(1)' },
            isRunning: true,
            isErrored: false,
            isInterrupted: false,
        };
        const ui = await $.ui.mount({ plugin: 'readable-session', surface: 'terminal', component: 'ToolUse', props });
        const row = (await ui.find({ text: /Writing/ }))?.text ?? '';
        expect(row).toContain('app/main.py · Python');
        await ui.redraw({ ...props, isRunning: false, output: { type: 'create' } });
        const done = (await ui.find({ text: /Wrote/ }))?.text ?? '';
        expect(done).toContain('Wrote');
        expect(done).not.toContain('Writing');
    });
});
describe('drawing on desktop', () => {
    test('the engine draws its own rows (no Nerd Font glyphs there)', async ($, on) => {
        on('ui.render', async ($x, e) => {
            const { Text } = $x.ui.resolve(e);
            return <Text>ENGINE</Text>;
        });
        const msg = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'desktop',
            component: 'UserMessage',
            props: { text: 'make my prompts visible', origin: { kind: 'composer' }, isExpanded: true },
        });
        expect(await msg.find({ text: /You prompted/ })).toBe(undefined);
        const row = await $.ui.mount({
            plugin: 'readable-session',
            surface: 'desktop',
            component: 'ToolUse',
            props: {
                tool_use_id: 't1',
                tool: 'Write',
                input: { file_path: 'C:/dev/app/main.py', content: 'print(1)' },
                isRunning: true,
                isErrored: false,
                isInterrupted: false,
            },
        });
        expect(await row.find({ text: /Writing/ })).toBe(undefined);
    });
});
