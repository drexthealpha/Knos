package knos.iris.pex;

import com.intersystems.enslib.pex.BusinessOperation;
import com.intersystems.enslib.pex.Message;
import com.intersystems.jdbc.IRISObject;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Sends a transaction Knos's own code built and signed (Embedded Python, Knos.Iris.Py.Tx) to Solana and confirms it.
 * It keeps no key and never signs: Java only submits. Settings: RpcURL, MaxConfirmS. With Mode=simulate (the default for
 * a transaction no relayer has signed) it asks simulateTransaction instead and reports the program's logs.
 */
public class SolanaSubmitOperation extends BusinessOperation {
    public String RpcURL = "https://api.devnet.solana.com";
    public String MaxConfirmS = "60";

    /** What comes back to the production. */
    public static class TxResult extends Message {
        public String signature = "";
        public long slot = 0;
        public String err = "";
        public String status = "";
        public String logs = "";
        public String explorer = "";
    }

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(20)).build();

    @Override
    public void OnInit() throws Exception {
        LOGINFO("SolanaSubmit ready: " + RpcURL);
    }

    @Override
    public void OnTearDown() throws Exception {
    }

    private String rpc(String method, String params) throws Exception {
        String body = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"" + method + "\",\"params\":" + params + "}";
        HttpRequest req = HttpRequest.newBuilder(URI.create(RpcURL)).timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build();
        return http.send(req, HttpResponse.BodyHandlers.ofString()).body();
    }

    private static String field(String json, String name) {
        Matcher m = Pattern.compile("\"" + name + "\"\\s*:\\s*(\"([^\"]*)\"|[-0-9]+|null|true|false)").matcher(json);
        return m.find() ? (m.group(2) != null ? m.group(2) : m.group(1)) : "";
    }

    @Override
    public Object OnMessage(Object request) throws Exception {
        IRISObject r = (IRISObject) request;
        String tx = r.invokeString("TxB64Get");
        String mode = r.invokeString("ModeGet");
        TxResult out = new TxResult();
        if (!"send".equals(mode)) {
            String got = rpc("simulateTransaction", "[\"" + tx + "\",{\"encoding\":\"base64\",\"sigVerify\":false,\"replaceRecentBlockhash\":true}]");
            out.status = "simulated";
            out.err = field(got, "err");
            out.slot = parseLong(field(got, "slot"));
            Matcher logs = Pattern.compile("\"logs\"\\s*:\\s*\\[(.*?)\\]").matcher(got);
            out.logs = logs.find() ? logs.group(1) : "";
            LOGINFO("simulateTransaction: err " + out.err + ", slot " + out.slot);
            return out;
        }
        String sent = rpc("sendTransaction", "[\"" + tx + "\",{\"encoding\":\"base64\",\"preflightCommitment\":\"confirmed\"}]");
        out.signature = field(sent, "result");
        if (out.signature.isEmpty()) {
            out.status = "refused";
            out.err = sent.length() > 400 ? sent.substring(0, 400) : sent;
            LOGWARNING("sendTransaction refused: " + out.err);
            return out;
        }
        out.explorer = "https://explorer.solana.com/tx/" + out.signature + "?cluster=devnet";
        long until = System.currentTimeMillis() + 1000L * Long.parseLong(MaxConfirmS);
        while (System.currentTimeMillis() < until) {
            String st = rpc("getSignatureStatuses", "[[\"" + out.signature + "\"],{\"searchTransactionHistory\":true}]");
            String conf = field(st, "confirmationStatus");
            if ("confirmed".equals(conf) || "finalized".equals(conf)) {
                out.status = conf;
                out.slot = parseLong(field(st, "slot"));
                out.err = field(st, "err");
                break;
            }
            Thread.sleep(1500);
        }
        if (out.status.isEmpty()) out.status = "unconfirmed after " + MaxConfirmS + " s";
        LOGINFO("sendTransaction " + out.signature + ": " + out.status);
        return out;
    }

    private static long parseLong(String s) {
        try { return Long.parseLong(s); } catch (NumberFormatException e) { return 0; }
    }
}
