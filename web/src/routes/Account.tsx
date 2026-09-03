/* The account screen moved to src/screens, where the brief puts it. This module
 * stays so App.tsx's route table does not have to be touched while another agent
 * may be editing it; it exports nothing of its own. */

export { AccountScreen } from '../screens/Account';
