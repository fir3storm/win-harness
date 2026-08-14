/**
 * CommandCode Mod: win-harness integration
 *
 * Exposes the win-harness tool harness as native tools within CommandCode.
 *
 * Installation:
 *   1. Ensure `win-harness` is installed globally (pip install -e . or install.bat)
 *   2. Copy this file to ~/.commandcode/mods/win-harness.mod.ts
 *   3. Restart CommandCode
 *
 * Usage in CommandCode:
 *   /win_harness_plan "Check running processes on Windows"
 *   /win_harness_recommend "Check for privilege escalation vectors"
 *   /win_harness_run ps_command --param command="Get-Process"
 *   /win_harness_stats
 */

import { ModApi } from '@commandcode/api';
import { execa } from 'execa';

export default async function winHarnessMod(api: ModApi) {
  /**
   * Run a security task through the harness — auto-plans and executes.
   * Usage: /win_harness_plan "Check running processes on Windows"
   */
  api.registerTool(
    'win_harness_plan',
    'Auto-plan and execute a Windows security task using the self-learning harness.',
    async (task: string) => {
      const { stdout } = await execa('win-harness', ['plan', task]);
      return stdout;
    }
  );

  /**
   * Get tool recommendations with confidence scores.
   * Usage: /win_harness_recommend "Check for privilege escalation vectors"
   */
  api.registerTool(
    'win_harness_recommend',
    'Get tool recommendations for a security task from the self-learning harness.',
    async (task: string) => {
      const { stdout } = await execa('win-harness', ['recommend', task]);
      return stdout;
    }
  );

  /**
   * Execute a specific tool with parameters.
   * Usage: /win_harness_run ps_command --param command="Get-Process"
   */
  api.registerTool(
    'win_harness_run',
    'Run a specific win-harness tool with parameters.',
    async (tool: string, params?: Record<string, string>) => {
      const args: string[] = ['run', tool];
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          args.push('-p', `${key}=${value}`);
        }
      }
      const { stdout } = await execa('win-harness', args);
      return stdout;
    }
  );

  /**
   * Show harness memory and performance statistics.
   * Usage: /win_harness_stats
   */
  api.registerTool(
    'win_harness_stats',
    'Show harness memory and performance statistics.',
    async () => {
      const { stdout } = await execa('win-harness', ['stats']);
      return stdout;
    }
  );
}
