import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		adapter: adapter({
            fallback: 'index.html', // Enable SPA mode
            pages: 'build',
            assets: 'build',
            precompress: false,
            strict: true
        })
	}
};

export default config;
