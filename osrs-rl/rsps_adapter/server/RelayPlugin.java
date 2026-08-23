import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.ServerSocket;
import java.net.Socket;

public class RelayPlugin implements Runnable {

    private static final int PORT = 43594;
    private static final int OBS_DIM = 12;
    private static final int N_ACTIONS = 6;

    private volatile boolean running = true;

    public void init() {
        Thread t = new Thread(this, "rl-relay");
        t.setDaemon(true);
        t.start();
    }

    @Override
    public void run() {
        try (ServerSocket server = new ServerSocket(PORT)) {
            while (running) {
                Socket client = server.accept();
                new Thread(() -> handle(client), "rl-session").start();
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void handle(Socket client) {
        try (BufferedReader in = new BufferedReader(
                new InputStreamReader(client.getInputStream()));
             PrintWriter out = new PrintWriter(client.getOutputStream(), true)) {

            String line;
            while ((line = in.readLine()) != null) {
                String[] cmd = line.split(",");
                if (cmd[0].equals("CLOSE")) break;
                if (cmd[0].equals("RESET")) {
                    resetFight();
                    out.println(response(0.0f, false));
                } else if (cmd[0].equals("STEP")) {
                    int action = Integer.parseInt(cmd[1]);
                    float reward = applyAction(action);
                    tickWorld();
                    boolean done = fightOver();
                    out.println(response(reward, done));
                    if (done) resetFight();
                } else {
                    out.println("ERR,unknown command");
                }
            }
        } catch (Exception e) {
            System.err.println("[RelayPlugin] session error: " + e);
        }
    }

    private String response(float reward, boolean done) {
        StringBuilder sb = new StringBuilder("OK,");
        sb.append(reward).append(',').append(done ? '1' : '0');
        for (float v : observe()) sb.append(',').append(v);
        for (boolean m : legalActions()) sb.append(',').append(m ? '1' : '0');
        return sb.toString();
    }

    private float[] observe() {
        // Wire these to your server's player/NPC state:
        // [hp/99, oppHp/99, food/10, oppFood/10, dist/8,
        //  cd/4, oppCd/4, prayer/max, oppPrayer/max,
        //  protect?1:0, oppProtect?1:0, ticksLeft/200]
        return new float[OBS_DIM];
    }

    private boolean[] legalActions() {
        // attack: in range && cooldown==0 | eat: food>0 && hp<max |
        // toward: dist>1 | away: room behind | protect: always | wait: always
        return new boolean[N_ACTIONS];
    }

    private float applyAction(int action) {
        // Map action index to your combat queue:
        // 0 attack, 1 eat, 2 move_toward, 3 move_away, 4 protect_toggle, 5 wait
        // Return shaped reward: +0.05*dmgDealt - 0.05*dmgTaken this step.
        return 0.0f;
    }

    private void tickWorld() {
        // Advance one game tick: cooldowns, protect drain, movement resolution.
    }

    private boolean fightOver() {
        // true when either fighter reaches 0 hp or tick cap reached.
        return false;
    }

    private void resetFight() {
        // Respawn/reset both fighters to start state.
    }
}
