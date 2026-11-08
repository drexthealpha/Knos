Class Knos.Iris.Production Extends Ens.Production
{
XData ProductionDefinition
{
<Production Name="Knos.Iris.Production" TestingEnabled="true" LogGeneralTraceEvents="false">
  <Description>Knos on IRIS: proof against a hash-locked Knos Ready brief, decided by an agent that can only say no or ask a person.</Description>
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
  <Item Name="FHIRLabIn" ClassName="Knos.Iris.BS.FhirFile" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="FileSpec">*.json</Setting>
  </Item>
  <Item Name="DeadlineWatch" ClassName="Knos.Iris.BS.DeadlineWatch" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="CallInterval">300</Setting>
  </Item>
  <Item Name="DailyDigest" ClassName="Knos.Iris.BS.DailyDigest" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="CallInterval">86400</Setting>
  </Item>
  <Item Name="SpendCapWatch" ClassName="Knos.Iris.BS.SpendCapWatch" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="CallInterval">60</Setting>
  </Item>
  <Item Name="ApproverReminder" ClassName="Knos.Iris.BS.ApproverReminder" PoolSize="1" Enabled="true">
    <Setting Target="Adapter" Name="CallInterval">3600</Setting>
  </Item>
  <Item Name="DecisionRouter" ClassName="EnsLib.MsgRouter.RoutingEngine" PoolSize="1" Enabled="true">
    <Setting Target="Host" Name="BusinessRuleName">Knos.Iris.Rule.DecisionRoutes</Setting>
  </Item>
  <Item Name="ReceiptFile" ClassName="Knos.Iris.BO.ReceiptFile" PoolSize="1" Enabled="true"/>
  <Item Name="DecisionFHIR" ClassName="Knos.Iris.BO.FhirTask" PoolSize="1" Enabled="true"/>
  <Item Name="ResultHL7Out" ClassName="EnsLib.HL7.Operation.FileOperation" PoolSize="1" Enabled="true">
    <Setting Target="Host" Name="Filename">decision%Q%!+(_a).hl7</Setting>
  </Item>
  <Item Name="DigestFile" ClassName="EnsLib.File.PassthroughOperation" PoolSize="1" Enabled="true">
    <Setting Target="Host" Name="Filename">%f_%Q.txt</Setting>
  </Item>
</Production>
}
}
