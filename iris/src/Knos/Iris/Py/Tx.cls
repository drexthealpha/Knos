/// The transaction the PAY branch hands to the Java PEX operation (SolanaSubmit), built by Knos's own code in Embedded
/// Python with solders: knos_pay's read-only version instruction from knos.settle.v2.pay, with the brief and the
/// amount in a memo beside it, unsigned by any key of Knos's (a throwaway fee payer). SolanaSubmit simulates it on
/// devnet (simulateTransaction, signatures not checked, the newest blockhash put in), so Visual Trace shows the PEX
/// run on every PAY and no money moves from inside IRIS.
Class Knos.Iris.Py.Tx Extends %RegisteredObject
{

ClassMethod Build(briefId As %String, amountUSDC As %Numeric) As %String [ Language = python ]
{
import base64
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from knos.settle.v2 import pay
payer = Keypair()
memo = Instruction(Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"), f"knos pay {briefId} {amountUSDC} USDC".encode()[:200], [])
tx = Transaction([payer], Message([pay.version_ix(), memo], payer.pubkey()), Hash.default())
return base64.b64encode(bytes(tx)).decode()
}

}
