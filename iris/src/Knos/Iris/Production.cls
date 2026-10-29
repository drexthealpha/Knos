Class Knos.Iris.Production Extends Ens.Production
{
XData ProductionDefinition
{
<Production Name="Knos.Iris.Production" TestingEnabled="true" LogGeneralTraceEvents="false">
  <Description>Knos Referee on IRIS: proof against a hash-locked Knos Ready brief, decided by an agent that can only say no or ask a person.</Description>
  <ActorPoolSize>2</ActorPoolSize>
  <Item Name="ProofIn" ClassName="Knos.Iris.BS.ProofIn" PoolSize="0" Enabled="true"/>
  <Item Name="BriefIn" ClassName="Knos.Iris.BS.BriefIn" PoolSize="0" Enabled="true"/>
  <Item Name="GitHubCheckRunPoller" ClassName="Knos.Iris.BS.CheckRunPoller" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="CallInterval">10</Setting>
  </Item>
  <Item Name="HL7LabIn" ClassName="Knos.Iris.BS.LabFile" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="FileSpec">*.hl7</Setting>
  </Item>
  <Item Name="ProofDecision" ClassName="Knos.Iris.BP.ProofDecision" PoolSize="1" Enabled="true"/>
  <Item Name="BriefLock" ClassName="Knos.Iris.BO.BriefLock" PoolSize="1" Enabled="true"/>
  <Item Name="Referee" ClassName="Knos.Iris.BO.Referee" PoolSize="1" Enabled="true"/>
  <Item Name="PayoutApprovers" ClassName="EnsLib.Workflow.Operation" PoolSize="1" Enabled="true">
    <Setting Target="Host" Name="AutoCreateRole">1</Setting>
  </Item>
  <Item Name="SolanaRead" ClassName="Knos.Iris.BO.SolanaRead" PoolSize="1" Enabled="true"/>
  <Item Name="SolanaSubmit" ClassName="EnsLib.PEX.BusinessOperation" PoolSize="1" Enabled="true">
    <Setting Target="Host" Name="%remoteClassname">knos.iris.pex.SolanaSubmitOperation</Setting>
    <Setting Target="Host" Name="%gatewayName">%Java Server</Setting>
    <Setting Target="Host" Name="%remoteSettings">RpcURL=https://api.devnet.solana.com</Setting>
  </Item>
  <Item Name="TraceSink" ClassName="Knos.Iris.BO.TraceSink" PoolSize="1" Enabled="true"/>
  <Item Name="Ens.Alert" ClassName="Knos.Iris.BO.Alert" PoolSize="1" Enabled="true"/>
</Production>
}
}
